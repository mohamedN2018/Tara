"""Server-side link previews, safe against SSRF.

The URL comes from a user, so nothing here trusts it:

- http/https on ports 80 and 443 only, no credentials in the URL;
- every address the host resolves to must be public. That check runs inside the
  connection itself and the socket connects to the checked address, so a DNS
  answer that changes between check and connect (rebinding) cannot get through;
- redirects are followed by hand, and each hop goes through the same checks;
- short timeouts, a deadline on the whole fetch (redirects included) and a byte
  cap on what is read, so a server that drips bytes cannot hold the consumer.

Only text is kept. Preview images are not fetched or stored: showing a remote
image would hand every reader's IP address to whoever wrote the post.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool

logger = logging.getLogger("tara.post.linkpreview")

CONNECT_TIMEOUT = 2.0
READ_TIMEOUT = 3.0
TOTAL_TIMEOUT = 8.0  # the whole fetch; one read may overrun it by READ_TIMEOUT
MAX_BYTES = 256 * 1024
MAX_REDIRECTS = 3
MAX_URL_LENGTH = 2000
ALLOWED_PORTS = {80, 443}
USER_AGENT = "TaraLinkPreview/1.0"

_URL_RE = re.compile(r"https?://[^\s<>\"'()]+", re.IGNORECASE)
_TRAILING_PUNCTUATION = ".,;:!?،؛؟"


# The NAT64 well-known prefix embeds an IPv4 target in its last 32 bits.
_NAT64 = ipaddress.IPv6Network("64:ff9b::/96")


class UnsafeURL(Exception):
    """The URL points somewhere the server must not go."""


def first_url(text: str) -> str | None:
    match = _URL_RE.search(text or "")
    return match.group(0).rstrip(_TRAILING_PUNCTUATION) if match else None


def is_public_address(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address):
        # Tunnelled forms carry an IPv4 target; judge that, not the wrapper.
        nat64 = ipaddress.IPv4Address(ip.packed[-4:]) if ip in _NAT64 else None
        for inner in (ip.ipv4_mapped, ip.sixtofour, ip.teredo[1] if ip.teredo else None, nat64):
            if inner is not None:
                ip = inner
                break
    # `is_global` excludes private, loopback, link-local (169.254.169.254 metadata
    # included), shared 100.64/10, reserved and documentation ranges.
    return ip.is_global and not ip.is_multicast


def public_addresses(host: str, port: int) -> list[str]:
    """Every address for ``host``, refusing the lot if any of them is not public."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise UnsafeURL(f"cannot resolve {host}") from exc
    addresses = [info[4][0] for info in infos]
    if not addresses or not all(is_public_address(a) for a in addresses):
        raise UnsafeURL(f"{host} is not a public address")
    return addresses


class _CheckedConnectionMixin:
    def _new_conn(self):
        address = public_addresses(self._dns_host, self.port)[0]
        return socket.create_connection((address, self.port), timeout=self.timeout)


class _CheckedHTTPConnection(_CheckedConnectionMixin, HTTPConnection):
    pass


class _CheckedHTTPSConnection(_CheckedConnectionMixin, HTTPSConnection):
    pass


class _CheckedHTTPPool(HTTPConnectionPool):
    ConnectionCls = _CheckedHTTPConnection


class _CheckedHTTPSPool(HTTPSConnectionPool):
    ConnectionCls = _CheckedHTTPSConnection


class _CheckedAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {
            "http": _CheckedHTTPPool,
            "https": _CheckedHTTPSPool,
        }


def _session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False  # never through an environment proxy
    adapter = _CheckedAdapter(max_retries=0)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def _check_url(url: str) -> None:
    if len(url) > MAX_URL_LENGTH:
        raise UnsafeURL("url too long")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UnsafeURL("scheme not allowed")
    if parts.username or parts.password:
        raise UnsafeURL("credentials in url")
    if not parts.hostname:
        raise UnsafeURL("no host")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        raise UnsafeURL("port not allowed")


def _check_deadline(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise TimeoutError("link preview took too long")


def _read_capped(response: requests.Response, deadline: float) -> bytes:
    """At most ``MAX_BYTES``, read before ``deadline``.

    ``read1`` returns what one socket read brings, so the deadline is checked
    between reads that each wait at most ``READ_TIMEOUT``.
    """
    body = b""
    while len(body) < MAX_BYTES:
        _check_deadline(deadline)
        chunk = response.raw.read1(16 * 1024, decode_content=True)
        if not chunk:
            break
        body += chunk
    return body[:MAX_BYTES]


def _decode(body: bytes, encoding: str | None) -> str:
    try:
        return body.decode(encoding or "utf-8", "replace")
    except LookupError:  # a charset Python does not know
        return body.decode("utf-8", "replace")


class _MetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            a = dict(attrs)
            key = (a.get("property") or a.get("name") or "").lower()
            if key and a.get("content"):
                self.meta.setdefault(key, a["content"])

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def _clean(value: str, limit: int) -> str:
    return " ".join((value or "").split())[:limit]


def parse_html(html: str, url: str) -> dict | None:
    parser = _MetaParser()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 - hostile markup is simply no preview
        return None
    title = _clean(parser.meta.get("og:title") or parser.title, 200)
    if not title:
        return None
    return {
        "url": url,
        "title": title,
        "description": _clean(
            parser.meta.get("og:description") or parser.meta.get("description", ""), 300
        ),
        "site": _clean(parser.meta.get("og:site_name") or urlsplit(url).hostname or "", 80),
    }


def fetch_preview(url: str) -> dict | None:
    """The preview for ``url``, or None for anything unsafe, broken or not HTML."""
    session = _session()
    current = url
    deadline = time.monotonic() + TOTAL_TIMEOUT
    try:
        for _ in range(MAX_REDIRECTS + 1):
            _check_url(current)
            _check_deadline(deadline)
            with session.get(
                current,
                stream=True,
                allow_redirects=False,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                # Uncompressed: the byte cap then bounds memory too.
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html",
                    "Accept-Encoding": "identity",
                },
            ) as response:
                if response.is_redirect:
                    current = urljoin(current, response.headers.get("location", ""))
                    continue
                if response.status_code != 200:
                    return None
                if "text/html" not in response.headers.get("content-type", "").lower():
                    return None
                body = _read_capped(response, deadline)
                return parse_html(_decode(body, response.encoding), current)
        return None  # too many redirects
    except UnsafeURL as exc:
        logger.info("link preview refused", extra={"reason": str(exc)})
        return None
    except (requests.RequestException, OSError, ValueError):
        logger.info("link preview failed", exc_info=True)
        return None
    finally:
        session.close()
