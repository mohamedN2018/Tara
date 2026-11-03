"""Dead-letter topology of the event bus, and its migration (roadmap 1.0c).

Target topology
---------------
One shared topic exchange ``<exchange>.dlx``. Each service's ``<queue>.dlq`` is bound to it
with the routing key ``<queue>`` only, and each main queue dead-letters with the routing key
``<queue>``, so a service's failures reach its own DLQ and no other.

- Queues declared from 1.0c on carry ``x-dead-letter-routing-key`` as a queue argument (the
  worker declares it).
- Queues declared before 1.0c have only ``x-dead-letter-exchange`` and cannot be redeclared
  with another argument (406 ``PRECONDITION_FAILED``). A per-queue policy ``tara-dlq-<queue>``
  supplies ``dead-letter-routing-key``. RabbitMQ resolves each dead-letter key on its own (the
  queue argument wins when both are set), so the policy fills in the missing key with no
  redeclare. Policies can later change without touching the queues.

Migration (``python -m tara_events.topology migrate``), every step idempotent:

1. bind each ``<queue>.dlq`` to the DLX with ``<queue>``;
2. set the per-queue policies and wait until RabbitMQ reports them applied (abort otherwise,
   before anything is unbound);
3. remove every other DLX binding of each DLQ (the legacy ``#``);
4. sort what already sits in the DLQs by origin queue (``x-death``): own messages stay, a
   foreign copy whose origin DLQ already holds the same event is dropped as a duplicate, any
   other foreign copy moves to its origin's DLQ (publisher confirms, then ack). Messages with
   no known origin stay where they are. Every message is counted before and after.

``rollback`` re-adds ``#`` and then deletes the policies, so there is no moment in which a dead
letter matches no binding.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger("tara.events.topology")

DLQ_SUFFIX = ".dlq"
LEGACY_BINDING = "#"
ORIGIN_HEADER = "x-tara-origin-queue"
POLICY_PREFIX = "tara-dlq-"
POLICY_PRIORITY = 10
_RETRY_SUFFIX = re.compile(r"\.retry\.\d+s$")


def dlx_name(exchange_name: str) -> str:
    return f"{exchange_name}.dlx"


def dlq_name(queue_name: str) -> str:
    return f"{queue_name}{DLQ_SUFFIX}"


def policy_name(queue_name: str) -> str:
    return f"{POLICY_PREFIX}{queue_name}"


def policy_for(queue_name: str, dlx: str) -> dict[str, Any]:
    return {
        "pattern": f"^{re.escape(queue_name)}$",
        "apply-to": "queues",
        "priority": POLICY_PRIORITY,
        "definition": {"dead-letter-exchange": dlx, "dead-letter-routing-key": queue_name},
    }


def _text(value: Any) -> str | None:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value if isinstance(value, str) and value else None


def origin_queue(headers: dict | None) -> str | None:
    """The main queue a dead letter came from, or ``None`` when the headers do not say."""
    headers = headers or {}
    origin = _text(headers.get(ORIGIN_HEADER)) or _text(headers.get("x-last-death-queue"))
    if origin is None:
        deaths = headers.get("x-death") or []
        if deaths and isinstance(deaths[0], dict):
            origin = _text(deaths[0].get("queue"))
    return _RETRY_SUFFIX.sub("", origin) if origin else None


@dataclass
class DeadLetter:
    dlq: str
    body: bytes | str
    headers: dict
    handle: Any = None  # transport-specific (delivery tag, raw message)

    def fingerprint(self) -> str:
        raw = self.body.encode() if isinstance(self.body, str) else self.body
        try:
            event_id = json.loads(raw).get("event_id")
        except (ValueError, AttributeError):
            event_id = None
        return f"event:{event_id}" if event_id else "sha256:" + hashlib.sha256(raw).hexdigest()


class Broker(Protocol):
    def main_queues(self, dlx: str) -> list[str]: ...
    def ensure_dlq(self, dlx: str, queue: str) -> None: ...
    def dlq_routing_keys(self, dlq: str, dlx: str) -> set[str]: ...
    def bind(self, dlq: str, dlx: str, routing_key: str) -> None: ...
    def unbind(self, dlq: str, dlx: str, routing_key: str) -> None: ...
    def policies(self) -> dict[str, dict]: ...
    def put_policy(self, name: str, policy: dict) -> None: ...
    def delete_policy(self, name: str) -> None: ...
    def applied_policy(self, queue: str) -> str | None: ...
    def count(self, queue: str) -> int: ...
    def exists(self, queue: str) -> bool: ...
    def fetch_all(self, dlq: str) -> list[DeadLetter]: ...
    def publish(self, target: str, letter: DeadLetter, headers: dict) -> None: ...
    def ack(self, letter: DeadLetter) -> None: ...
    def release(self) -> None: ...


@dataclass
class Report:
    dry_run: bool
    queues: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    before: dict[str, int] = field(default_factory=dict)
    after: dict[str, int] = field(default_factory=dict)
    fetched: Counter = field(default_factory=Counter)
    kept: Counter = field(default_factory=Counter)
    moved_out: Counter = field(default_factory=Counter)
    moved_in: Counter = field(default_factory=Counter)
    dropped: Counter = field(default_factory=Counter)
    unknown_origin: Counter = field(default_factory=Counter)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def as_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "ok": self.ok,
            "queues": self.queues,
            "actions": self.actions,
            "dlq": {
                dlq_name(q): {
                    "before": self.before.get(dlq_name(q), 0),
                    "fetched": self.fetched[dlq_name(q)],
                    "kept": self.kept[dlq_name(q)],
                    "moved_out": self.moved_out[dlq_name(q)],
                    "moved_in": self.moved_in[dlq_name(q)],
                    "dropped_duplicates": self.dropped[dlq_name(q)],
                    "unknown_origin": self.unknown_origin[dlq_name(q)],
                    "after": self.after.get(dlq_name(q)),
                }
                for q in self.queues
            },
            "totals": {
                "before": sum(self.before.values()),
                "moved": sum(self.moved_out.values()),
                "dropped_duplicates": sum(self.dropped.values()),
                "after": sum(self.after.values()) if self.after else None,
            },
            "problems": self.problems,
        }


def plan_cleanup(
    fetched: dict[str, list[DeadLetter]], queues: set[str], *, keep_duplicates: bool = False
) -> list[tuple[DeadLetter, str, str | None]]:
    """Decide the fate of every fetched dead letter: ``keep``, ``move`` (to a DLQ) or ``drop``.

    A message is only dropped when its origin DLQ keeps an identical event, so no event that
    exists once in the DLQs is ever removed.
    """
    present: dict[str, set[str]] = defaultdict(set)
    for dlq, letters in fetched.items():
        own = dlq[: -len(DLQ_SUFFIX)]
        for letter in letters:
            if origin_queue(letter.headers) == own:
                present[own].add(letter.fingerprint())

    decisions: list[tuple[DeadLetter, str, str | None]] = []
    for dlq, letters in fetched.items():
        own = dlq[: -len(DLQ_SUFFIX)]
        for letter in letters:
            origin = origin_queue(letter.headers)
            if origin is None or origin == own or origin not in queues:
                decisions.append((letter, "keep", None))
                continue
            fingerprint = letter.fingerprint()
            if fingerprint in present[origin] and not keep_duplicates:
                decisions.append((letter, "drop", None))
            else:
                present[origin].add(fingerprint)
                decisions.append((letter, "move", dlq_name(origin)))
    return decisions


def discover_queues(broker: Broker, dlx: str) -> list[str]:
    """Main queues that dead-letter into ``dlx``, plus owners of DLQs bound to it."""
    return sorted(set(broker.main_queues(dlx)))


def _wait_for_policies(broker: Broker, queues: list[str], timeout: float) -> list[str]:
    deadline = time.monotonic() + timeout
    while True:
        missing = [
            q for q in queues if broker.exists(q) and broker.applied_policy(q) != policy_name(q)
        ]
        if not missing or time.monotonic() >= deadline:
            return missing
        time.sleep(0.5)


def migrate(
    broker: Broker,
    *,
    exchange: str,
    queues: list[str] | None = None,
    dry_run: bool = False,
    keep_duplicates: bool = False,
    policy_timeout: float = 15.0,
) -> Report:
    dlx = dlx_name(exchange)
    report = Report(dry_run=dry_run, queues=list(queues or discover_queues(broker, dlx)))
    act = report.actions.append

    # 1. Own binding for every DLQ (creates the DLQ when a service never had one).
    for q in report.queues:
        if q not in broker.dlq_routing_keys(dlq_name(q), dlx):
            act(f"bind {dlq_name(q)} <- {dlx} [{q}]")
            if not dry_run:
                broker.ensure_dlq(dlx, q)

    # 2. Per-queue policies supplying the dead-letter routing key.
    existing = broker.policies()
    for q in report.queues:
        wanted = policy_for(q, dlx)
        current = existing.get(policy_name(q))
        if current is None or any(current.get(k) != v for k, v in wanted.items()):
            act(f"set policy {policy_name(q)} {json.dumps(wanted['definition'], sort_keys=True)}")
            if not dry_run:
                broker.put_policy(policy_name(q), wanted)
    if not dry_run:
        missing = _wait_for_policies(broker, report.queues, policy_timeout)
        if missing:
            report.problems.append(
                "policy not applied (another policy with a higher priority?): "
                + ", ".join(missing)
                + "; nothing was unbound"
            )
            return report

    # 3. Remove the legacy catch-all (and any other foreign) DLX bindings.
    for q in report.queues:
        for rk in sorted(broker.dlq_routing_keys(dlq_name(q), dlx) - {q}):
            act(f"unbind {dlq_name(q)} <- {dlx} [{rk}]")
            if not dry_run:
                broker.unbind(dlq_name(q), dlx, rk)

    # 4. Sort the messages already dead-lettered.
    dlqs = [dlq_name(q) for q in report.queues if broker.exists(dlq_name(q))]
    report.before = {d: broker.count(d) for d in dlqs}
    try:
        fetched = {d: broker.fetch_all(d) for d in dlqs}
        decisions = plan_cleanup(fetched, set(report.queues), keep_duplicates=keep_duplicates)
        for letter, fate, target in decisions:
            report.fetched[letter.dlq] += 1
            if fate == "keep":
                report.kept[letter.dlq] += 1
                if origin_queue(letter.headers) not in report.queues:
                    report.unknown_origin[letter.dlq] += 1
            elif fate == "drop":
                report.dropped[letter.dlq] += 1
                if not dry_run:
                    broker.ack(letter)
            else:
                report.moved_out[letter.dlq] += 1
                report.moved_in[target] += 1
                if not dry_run:
                    origin = origin_queue(letter.headers)
                    broker.publish(target, letter, {**letter.headers, ORIGIN_HEADER: origin})
                    broker.ack(letter)
    finally:
        broker.release()  # everything not acked goes back to its queue
    report.after = {d: broker.count(d) for d in dlqs}

    for d in dlqs:
        if report.fetched[d] != report.before[d]:
            report.problems.append(
                f"{d}: counted {report.before[d]} but fetched {report.fetched[d]} "
                "(new dead letters arrived during the run? re-run to sort them)"
            )
        expected = report.before[d] if dry_run else report.kept[d] + report.moved_in[d]
        if report.after[d] < expected:
            report.problems.append(
                f"{d}: expected at least {expected} after, found {report.after[d]}"
            )
    return report


def rollback(broker: Broker, *, exchange: str, queues: list[str] | None = None) -> Report:
    """Restore the pre-1.0c routing: ``#`` first, then remove the policies."""
    dlx = dlx_name(exchange)
    report = Report(dry_run=False, queues=list(queues or discover_queues(broker, dlx)))
    for q in report.queues:
        if LEGACY_BINDING not in broker.dlq_routing_keys(dlq_name(q), dlx):
            report.actions.append(f"bind {dlq_name(q)} <- {dlx} [{LEGACY_BINDING}]")
            broker.bind(dlq_name(q), dlx, LEGACY_BINDING)
    existing = broker.policies()
    for q in report.queues:
        if policy_name(q) in existing:
            report.actions.append(f"delete policy {policy_name(q)}")
            broker.delete_policy(policy_name(q))
    return report


def status(broker: Broker, *, exchange: str, queues: list[str] | None = None) -> Report:
    """Read-only check: each queue has its policy (or argument) and only its own DLQ binding."""
    dlx = dlx_name(exchange)
    report = Report(dry_run=True, queues=list(queues or discover_queues(broker, dlx)))
    for q in report.queues:
        keys = broker.dlq_routing_keys(dlq_name(q), dlx)
        if broker.exists(dlq_name(q)):
            report.before[dlq_name(q)] = broker.count(dlq_name(q))
        if keys != {q}:
            report.problems.append(f"{dlq_name(q)} bindings {sorted(keys)} (want [{q!r}])")
        if broker.exists(q) and broker.applied_policy(q) != policy_name(q):
            report.problems.append(f"{q}: policy {policy_name(q)} not applied")
    return report


# --- RabbitMQ adapter -----------------------------------------------------------------------


class ManagementAPI:
    """Tiny client for the RabbitMQ management HTTP API (stdlib only)."""

    def __init__(self, base_url: str, user: str, password: str, vhost: str = "/") -> None:
        if urllib.parse.urlsplit(base_url).scheme not in ("http", "https"):
            raise ValueError("management URL must be http(s)")
        self.base_url = base_url.rstrip("/")
        self.vhost = urllib.parse.quote(vhost, safe="")
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        self._auth = f"Basic {token}"

    def request(self, method: str, path: str, body: Any = None, *, ok_404: bool = False) -> Any:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(  # noqa: S310 - scheme checked in __init__
            self.base_url + path, data=data, method=method
        )
        req.add_header("Authorization", self._auth)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            if ok_404 and exc.code == 404:
                return None
            raise
        return json.loads(raw) if raw else None

    def quote(self, name: str) -> str:
        return urllib.parse.quote(name, safe="")

    def definitions(self) -> dict:
        return self.request("GET", "/api/definitions")


class RabbitBroker:
    """``Broker`` over AMQP (bindings, counts, messages) plus the management API (policies)."""

    def __init__(self, connection, api: ManagementAPI) -> None:
        self.connection = connection
        self.api = api
        self._get_channel = None
        self._pending: list[DeadLetter] = []

    def _channel(self):
        return self.connection.channel()

    def main_queues(self, dlx: str) -> list[str]:
        found = set()
        for q in self.api.request("GET", f"/api/queues/{self.api.vhost}?columns=name,arguments"):
            name = q["name"]
            args = q.get("arguments") or {}
            if args.get("x-dead-letter-exchange") == dlx and not name.endswith(DLQ_SUFFIX):
                found.add(name)
            elif name.endswith(DLQ_SUFFIX) and self.dlq_routing_keys(name, dlx):
                found.add(name[: -len(DLQ_SUFFIX)])
        return sorted(found)

    def ensure_dlq(self, dlx: str, queue: str) -> None:
        ch = self._channel()
        try:
            ch.exchange_declare(dlx, "topic", durable=True, auto_delete=False)
            ch.queue_declare(dlq_name(queue), durable=True, auto_delete=False)
            ch.queue_bind(dlq_name(queue), dlx, queue)
        finally:
            ch.close()

    def dlq_routing_keys(self, dlq: str, dlx: str) -> set[str]:
        rows = self.api.request(
            "GET", f"/api/queues/{self.api.vhost}/{self.api.quote(dlq)}/bindings", ok_404=True
        )
        return {b["routing_key"] for b in rows or [] if b.get("source") == dlx}

    def bind(self, dlq: str, dlx: str, routing_key: str) -> None:
        ch = self._channel()
        try:
            ch.queue_bind(dlq, dlx, routing_key)
        finally:
            ch.close()

    def unbind(self, dlq: str, dlx: str, routing_key: str) -> None:
        ch = self._channel()
        try:
            ch.queue_unbind(dlq, dlx, routing_key)
        finally:
            ch.close()

    def policies(self) -> dict[str, dict]:
        rows = self.api.request("GET", f"/api/policies/{self.api.vhost}") or []
        return {p["name"]: p for p in rows}

    def put_policy(self, name: str, policy: dict) -> None:
        self.api.request("PUT", f"/api/policies/{self.api.vhost}/{self.api.quote(name)}", policy)

    def delete_policy(self, name: str) -> None:
        self.api.request(
            "DELETE", f"/api/policies/{self.api.vhost}/{self.api.quote(name)}", ok_404=True
        )

    def applied_policy(self, queue: str) -> str | None:
        row = self.api.request(
            "GET", f"/api/queues/{self.api.vhost}/{self.api.quote(queue)}", ok_404=True
        )
        return (row or {}).get("policy") or None

    def exists(self, queue: str) -> bool:
        from amqp.exceptions import NotFound

        ch = self._channel()
        try:
            ch.queue_declare(queue, passive=True)
            return True
        except NotFound:
            return False
        finally:
            try:
                ch.close()
            except Exception:  # noqa: S110 - the broker already closed it after a 404
                pass

    def count(self, queue: str) -> int:
        ch = self._channel()
        try:
            return ch.queue_declare(queue, passive=True).message_count
        finally:
            ch.close()

    def fetch_all(self, dlq: str) -> list[DeadLetter]:
        """Get every ready message without acking; ``release`` requeues what is left."""
        if self._get_channel is None:
            self._get_channel = self._channel()
        letters = []
        while True:
            msg = self._get_channel.basic_get(queue=dlq, no_ack=False)
            if msg is None:
                break
            headers = dict(msg.properties.get("application_headers") or {})
            letter = DeadLetter(dlq=dlq, body=msg.body, headers=headers, handle=msg)
            letters.append(letter)
            self._pending.append(letter)
        return letters

    def publish(self, target: str, letter: DeadLetter, headers: dict) -> None:
        from amqp import Message

        ch = self._channel()
        try:
            ch.queue_declare(target, passive=True)  # never publish into nothing
            props = {
                k: v for k, v in letter.handle.properties.items() if k != "application_headers"
            }
            props["delivery_mode"] = 2
            # Waits for the broker's ack and raises if it nacks: only then is the source acked.
            ch.basic_publish_confirm(
                Message(letter.body, application_headers=headers, **props),
                exchange="",
                routing_key=target,
            )
        finally:
            ch.close()

    def ack(self, letter: DeadLetter) -> None:
        self._get_channel.basic_ack(letter.handle.delivery_tag)
        self._pending.remove(letter)

    def release(self) -> None:
        if self._get_channel is None:
            return
        for letter in self._pending:
            self._get_channel.basic_reject(letter.handle.delivery_tag, requeue=True)
        self._pending.clear()
        self._get_channel.close()
        self._get_channel = None


def connect(broker_url: str, management_url: str | None = None):
    """Open a confirm-mode AMQP connection and the matching management client."""
    from kombu import Connection

    conn = Connection(broker_url, transport_options={"confirm_publish": True})
    mgmt = management_url or os.getenv("RABBITMQ_MANAGEMENT_URL") or f"http://{conn.hostname}:15672"
    api = ManagementAPI(mgmt, conn.userid, conn.password, conn.virtual_host or "/")
    conn.connect()
    return conn, api


def _print_report(report: Report, as_json: bool) -> None:
    data = report.as_dict()
    if as_json:
        print(json.dumps(data, indent=2, sort_keys=True))
        return
    print(("DRY RUN - nothing changed" if report.dry_run else "APPLIED") + f"; ok={report.ok}")
    for line in report.actions:
        print("  " + line)
    if not report.actions:
        print("  (no topology changes needed)")
    print(f"  {'dlq':34} before fetched kept moved_out moved_in dropped unknown after")
    for name, row in data["dlq"].items():
        print(
            f"  {name:34} {row['before']:6} {row['fetched']:7} {row['kept']:4} "
            f"{row['moved_out']:9} {row['moved_in']:8} {row['dropped_duplicates']:7} "
            f"{row['unknown_origin']:7} {row['after'] if row['after'] is not None else '-':>5}"
        )
    print("  totals: " + json.dumps(data["totals"], sort_keys=True))
    for problem in report.problems:
        print("  PROBLEM: " + problem)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tara_events.topology", description=__doc__)
    parser.add_argument("command", choices=["status", "migrate", "rollback", "export"])
    parser.add_argument("--broker-url", default=os.getenv("RABBITMQ_URL", ""))
    parser.add_argument("--management-url", default=None)
    parser.add_argument("--exchange", default=os.getenv("TARA_EVENT_EXCHANGE", "tara.events"))
    parser.add_argument("--queue", action="append", help="limit to these main queues")
    parser.add_argument("--dry-run", action="store_true", help="migrate: report only")
    parser.add_argument(
        "--keep-duplicates",
        action="store_true",
        help="migrate: move foreign copies even when the origin DLQ already has the event",
    )
    parser.add_argument("--output", help="export: write the broker definitions to this file")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if not args.broker_url:
        parser.error("no broker URL (set RABBITMQ_URL or pass --broker-url)")

    conn, api = connect(args.broker_url, args.management_url)
    try:
        if args.command == "export":
            data = json.dumps(api.definitions(), indent=2, sort_keys=True)
            if args.output:
                with open(args.output, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(data + "\n")
            else:
                print(data)
            return 0
        broker = RabbitBroker(conn, api)
        if args.command == "migrate":
            report = migrate(
                broker,
                exchange=args.exchange,
                queues=args.queue,
                dry_run=args.dry_run,
                keep_duplicates=args.keep_duplicates,
            )
        elif args.command == "rollback":
            report = rollback(broker, exchange=args.exchange, queues=args.queue)
        else:
            report = status(broker, exchange=args.exchange, queues=args.queue)
        _print_report(report, args.json)
        return 0 if report.ok else 1
    finally:
        conn.release()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
