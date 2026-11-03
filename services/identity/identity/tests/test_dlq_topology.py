"""Per-service dead-letter routing (roadmap 1.0c): worker declarations and the migration.

``FakeBroker`` models the parts of RabbitMQ the migration relies on: topic bindings on the
DLX, per-key dead-letter settings where a queue argument wins over a policy, and unacked
messages going back to their queue on release.
"""

from __future__ import annotations

import json
from collections import defaultdict
from unittest.mock import MagicMock

from amqp.exceptions import PreconditionFailed
from kombu import Connection

from tara_events import topology, worker

QUEUES = ["feed.events", "graph.events", "post.events"]
DLX = "tara.events.dlx"


class FakeBroker:
    def __init__(self, queues=QUEUES, *, legacy=True):
        self.args = {
            q: {"x-dead-letter-exchange": DLX}
            if legacy
            else {"x-dead-letter-exchange": DLX, "x-dead-letter-routing-key": q}
            for q in queues
        }
        self.messages = defaultdict(list)
        self.bindings = {(topology.dlq_name(q), "#" if legacy else q) for q in queues}
        self._policies = {}
        self.policy_blocked = False
        self._unacked = []

    # RabbitMQ behaviour -------------------------------------------------------------
    def _setting(self, queue, key):
        arg = self.args[queue].get(f"x-{key}")
        if arg is not None:
            return arg
        name = self.applied_policy(queue)
        return self._policies[name]["definition"].get(key) if name else None

    def dead_letter(self, queue, body, routing_key):
        """A consumer of ``queue`` rejected a message published with ``routing_key``."""
        rk = self._setting(queue, "dead-letter-routing-key") or routing_key
        assert self._setting(queue, "dead-letter-exchange") == DLX
        headers = {"x-death": [{"queue": queue, "reason": "rejected"}]}
        for dlq, key in sorted(self.bindings):
            if key in ("#", rk):
                self.messages[dlq].append((json.dumps(body), dict(headers)))

    # Broker protocol ----------------------------------------------------------------
    def main_queues(self, dlx):
        return sorted(self.args)

    def ensure_dlq(self, dlx, queue):
        self.bindings.add((topology.dlq_name(queue), queue))

    def dlq_routing_keys(self, dlq, dlx):
        return {rk for d, rk in self.bindings if d == dlq}

    def bind(self, dlq, dlx, routing_key):
        self.bindings.add((dlq, routing_key))

    def unbind(self, dlq, dlx, routing_key):
        self.bindings.discard((dlq, routing_key))

    def policies(self):
        return {k: dict(v, name=k) for k, v in self._policies.items()}

    def put_policy(self, name, policy):
        self._policies[name] = policy

    def delete_policy(self, name):
        self._policies.pop(name, None)

    def applied_policy(self, queue):
        if self.policy_blocked:
            return "someone-elses-policy"
        name = topology.policy_name(queue)
        return name if name in self._policies else None

    def exists(self, queue):
        return queue in self.args or queue.endswith(".dlq")

    def count(self, queue):
        return len(self.messages[queue])

    def fetch_all(self, dlq):
        letters = []
        for body, headers in self.messages.pop(dlq, []):
            letter = topology.DeadLetter(dlq=dlq, body=body, headers=headers)
            self._unacked.append(letter)
            letters.append(letter)
        return letters

    def publish(self, target, letter, headers):
        self.messages[target].append((letter.body, headers))

    def ack(self, letter):
        self._unacked.remove(letter)

    def release(self):
        for letter in self._unacked:
            self.messages[letter.dlq].append((letter.body, letter.headers))
        self._unacked.clear()


def _event(event_id):
    return {"event_id": event_id, "event_type": "post.created", "subject_id": "s"}


def _events_in(broker, queue):
    return sorted(str(json.loads(body).get("event_id")) for body, _ in broker.messages[queue])


# --- dead-letter routing --------------------------------------------------------------


def test_worker_declares_own_dead_letter_routing():
    w = worker.EventWorker(
        Connection("memory://"), exchange_name="tara.events", queue_name="feed.events"
    )
    assert w.dlq.name == "feed.events.dlq"
    assert w.dlq.routing_key == "feed.events"  # not "#"
    assert w.queue.queue_arguments == {
        "x-dead-letter-exchange": "tara.events.dlx",
        "x-dead-letter-routing-key": "feed.events",
    }
    # Retry queues are untouched and still return to the main queue.
    assert w.retry_queues[0].queue_arguments["x-dead-letter-routing-key"] == "feed.events"


def test_legacy_topology_fans_out_and_migration_routes_to_own_dlq_only():
    broker = FakeBroker()
    broker.dead_letter("feed.events", _event("before"), "post.created")
    assert {q: broker.count(topology.dlq_name(q)) for q in QUEUES} == dict.fromkeys(QUEUES, 1)

    topology.migrate(broker, exchange="tara.events")
    broker.dead_letter("feed.events", _event("after"), "post.created")
    broker.dead_letter("graph.events", _event("graph"), "post.created")

    assert _events_in(broker, "feed.events.dlq") == ["after", "before"]
    assert _events_in(broker, "graph.events.dlq") == ["graph"]
    assert _events_in(broker, "post.events.dlq") == []


def test_new_install_routes_by_queue_argument_without_policy():
    broker = FakeBroker(legacy=False)
    broker.dead_letter("post.events", _event("p"), "post.created")
    assert _events_in(broker, "post.events.dlq") == ["p"]
    assert broker.count("feed.events.dlq") == 0


def test_origin_queue_reads_x_death_and_moved_header():
    assert topology.origin_queue({"x-death": [{"queue": "feed.events"}]}) == "feed.events"
    assert topology.origin_queue({"x-death": [{"queue": b"feed.events.retry.30s"}]}) == (
        "feed.events"
    )
    assert topology.origin_queue({topology.ORIGIN_HEADER: "post.events"}) == "post.events"
    assert topology.origin_queue({}) is None


def test_replay_only_takes_this_queues_dead_letters():
    assert worker.should_replay({"x-death": [{"queue": "feed.events"}]}, "feed.events")
    assert worker.should_replay({}, "feed.events")  # unknown origin: old behaviour
    assert not worker.should_replay({"x-death": [{"queue": "graph.events"}]}, "feed.events")


# --- redeclare mismatch ---------------------------------------------------------------


def _channel():
    ch = MagicMock()
    ch.prepare_queue_arguments.side_effect = lambda args, **kw: args
    return ch


def test_redeclare_mismatch_falls_back_to_passive_declare_and_binds():
    first, second = _channel(), _channel()
    first.queue_declare.side_effect = PreconditionFailed("inequivalent arg")
    connection = MagicMock()
    connection.channel.side_effect = [first, second]
    w = worker.EventWorker(Connection("memory://"), exchange_name="x", queue_name="q")
    w.queue.bindings = {worker.binding(w.exchange, routing_key="post.created")}

    assert worker.declare_main_queue(connection, w.queue) is True

    kwargs = second.queue_declare.call_args.kwargs
    assert kwargs["passive"] is True and kwargs["queue"] == "q"
    bound = {c.kwargs.get("routing_key") for c in second.queue_bind.call_args_list}
    assert "post.created" in bound
    first.close.assert_called()
    second.close.assert_called()


def test_matching_declare_reports_new_topology():
    ch = _channel()
    connection = MagicMock()
    connection.channel.return_value = ch
    w = worker.EventWorker(Connection("memory://"), exchange_name="x", queue_name="q")

    assert worker.declare_main_queue(connection, w.queue) is False
    assert ch.queue_declare.call_args.kwargs["passive"] is False
    assert ch.queue_declare.call_args.kwargs["arguments"]["x-dead-letter-routing-key"] == "q"


def test_consumer_does_not_redeclare_the_main_queue():
    w = worker.EventWorker(Connection("memory://"), exchange_name="x", queue_name="q")
    w.dlx = MagicMock()
    w.dlq = MagicMock()
    w.retry_queues = []
    channel = _channel()
    channel.connection.channel.return_value = _channel()
    consumer_cls = MagicMock()

    w.get_consumers(consumer_cls, channel)

    (queue,) = consumer_cls.call_args.kwargs["queues"]
    assert queue.name == "q" and queue.no_declare


# --- migration ------------------------------------------------------------------------


def _legacy_with_backlog():
    broker = FakeBroker()
    broker.dead_letter("feed.events", _event("f1"), "post.created")  # copies in all 3
    broker.dead_letter("graph.events", _event("g1"), "post.created")  # copies in all 3
    # feed's own copy of f1 was replayed earlier: only foreign copies remain.
    broker.messages["feed.events.dlq"] = [
        m for m in broker.messages["feed.events.dlq"] if json.loads(m[0])["event_id"] != "f1"
    ]
    broker.messages["post.events.dlq"].append((json.dumps({"x": 1}), {}))  # unknown origin
    return broker


def test_dry_run_changes_nothing():
    broker = _legacy_with_backlog()
    before = {k: list(v) for k, v in broker.messages.items()}

    report = topology.migrate(broker, exchange="tara.events", dry_run=True)

    assert report.ok, report.problems
    assert broker.messages == before
    assert ("feed.events.dlq", "#") in broker.bindings and not broker._policies
    assert sum(report.moved_out.values()) == 1
    assert sum(report.dropped.values()) == 3


def test_migration_moves_dedupes_and_counts():
    broker = _legacy_with_backlog()

    report = topology.migrate(broker, exchange="tara.events")

    assert report.ok, report.problems
    assert report.before == {"feed.events.dlq": 1, "graph.events.dlq": 2, "post.events.dlq": 3}
    # f1: one foreign copy moved home, the other dropped; g1: two foreign copies dropped.
    assert _events_in(broker, "feed.events.dlq") == ["f1"]
    assert _events_in(broker, "graph.events.dlq") == ["g1"]
    assert broker.count("post.events.dlq") == 1  # the unknown-origin message stays
    assert sum(report.before.values()) - sum(report.dropped.values()) == sum(report.after.values())
    moved_body, moved_headers = broker.messages["feed.events.dlq"][0]
    assert moved_headers[topology.ORIGIN_HEADER] == "feed.events"
    assert broker.bindings == {(topology.dlq_name(q), q) for q in QUEUES}
    assert set(broker._policies) == {topology.policy_name(q) for q in QUEUES}
    assert broker._policies["tara-dlq-feed.events"]["pattern"] == r"^feed\.events$"


def test_migration_is_idempotent():
    broker = _legacy_with_backlog()
    topology.migrate(broker, exchange="tara.events")
    state = ({k: list(v) for k, v in broker.messages.items()}, set(broker.bindings))

    again = topology.migrate(broker, exchange="tara.events")

    assert again.ok and again.actions == []
    assert sum(again.moved_out.values()) == sum(again.dropped.values()) == 0
    assert ({k: list(v) for k, v in broker.messages.items()}, set(broker.bindings)) == state
    assert topology.status(broker, exchange="tara.events").ok


def test_keep_duplicates_moves_every_foreign_copy():
    broker = _legacy_with_backlog()
    report = topology.migrate(broker, exchange="tara.events", keep_duplicates=True)
    assert sum(report.dropped.values()) == 0
    assert sum(report.after.values()) == sum(report.before.values())


def test_migration_aborts_before_unbinding_when_policy_is_shadowed():
    broker = _legacy_with_backlog()
    broker.policy_blocked = True

    report = topology.migrate(broker, exchange="tara.events", policy_timeout=0)

    assert not report.ok
    assert ("feed.events.dlq", "#") in broker.bindings  # nothing unbound, nothing moved
    assert broker.count("graph.events.dlq") == 2


def test_rollback_restores_fan_out():
    broker = _legacy_with_backlog()
    topology.migrate(broker, exchange="tara.events")

    topology.rollback(broker, exchange="tara.events")
    topology.rollback(broker, exchange="tara.events")  # safe to repeat

    assert not broker._policies
    assert all((topology.dlq_name(q), "#") in broker.bindings for q in QUEUES)
    broker.dead_letter("feed.events", _event("x"), "post.created")
    assert all("x" in _events_in(broker, topology.dlq_name(q)) for q in QUEUES)


def test_status_flags_unmigrated_topology():
    report = topology.status(FakeBroker(), exchange="tara.events")
    assert not report.ok
    assert any("bindings ['#']" in p for p in report.problems)
