"""Link previews: SSRF refusals, on real sockets where the behaviour lives there."""

import socket
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from posts import linkpreview, services
from posts.linkpreview import UnsafeURL, fetch_preview, first_url, is_public_address
from posts.models import Post

PAGE = (
    b"<html><head><title>Plain title</title>"
    b'<meta property="og:title" content="OG &amp; title">'
    b'<meta name="description" content="A  description">'
    b"</head></html>"
)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/page":
            self._send(200, PAGE)
        elif self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", self.server.redirect_to)
            self.end_headers()
        elif self.path == "/loop":
            self.send_response(302)
            self.send_header("Location", "/loop")
            self.end_headers()
        elif self.path == "/json":
            self._send(200, b"{}", "application/json")
        elif self.path == "/badcharset":
            self._send(200, PAGE, "text/html; charset=x-no-such-charset")
        elif self.path == "/slow":
            # Headers at once, then the body a byte at a time, never finishing.
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            try:
                self.wfile.write(b"<title>slow</title>")
                for _ in range(200):
                    self.wfile.write(b" ")
                    self.wfile.flush()
                    time.sleep(0.05)
            except OSError:
                pass  # the client gave up
        elif self.path == "/huge":
            head = b"<title>huge</title>"
            self._send(200, head + b"x" * (5 * 1024 * 1024))
        else:
            self._send(404, b"")
        self.server.hits.append(self.path)

    def _send(self, status, body, content_type="text/html; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass  # the client stopped reading at its byte cap

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    httpd.hits = []
    httpd.redirect_to = "/page"
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()


@pytest.fixture
def local_is_public(monkeypatch, server):
    """Treat the test server as public. Port checks are lifted for it alone."""
    monkeypatch.setattr(linkpreview, "is_public_address", lambda a: a == "127.0.0.1")
    monkeypatch.setattr(linkpreview, "ALLOWED_PORTS", {80, 443, server.server_port})


def _url(server, path):
    return f"http://127.0.0.1:{server.server_port}{path}"


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.5",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",  # cloud metadata
        "100.64.0.1",
        "0.0.0.0",  # noqa: S104
        "224.0.0.1",
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:127.0.0.1",
        "::ffff:169.254.169.254",
        "2002:7f00:1::",  # 6to4 wrapping 127.0.0.1
        "64:ff9b::a9fe:a9fe",  # NAT64 wrapping 169.254.169.254
        "64:ff9b::a00:5",  # NAT64 wrapping 10.0.0.5
    ],
)
def test_non_public_addresses_are_refused(address):
    assert is_public_address(address) is False


@pytest.mark.parametrize("address", ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"])
def test_public_addresses_pass(address):
    assert is_public_address(address) is True


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/",
        "file:///etc/passwd",
        "gopher://example.com/",
        "http://user:pw@example.com/",
        "http://example.com:8080/",
        "http://example.com:22/",
        "http://" + "a" * 3000 + ".com/",
    ],
)
def test_bad_urls_fail_before_any_connection(url, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no connection may be attempted")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    assert fetch_preview(url) is None


def test_loopback_server_is_not_reached(server, monkeypatch):
    monkeypatch.setattr(linkpreview, "ALLOWED_PORTS", {80, 443, server.server_port})
    assert fetch_preview(_url(server, "/page")) is None
    assert server.hits == []


def test_hostname_resolving_to_private_is_refused(server, monkeypatch):
    monkeypatch.setattr(linkpreview, "ALLOWED_PORTS", {80, 443, server.server_port})
    real = socket.getaddrinfo
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, **k: real("127.0.0.1", port, **k) if host == "evil.test" else None,
    )
    assert fetch_preview(f"http://evil.test:{server.server_port}/page") is None
    assert server.hits == []


def test_one_private_answer_among_public_ones_is_refused(monkeypatch):
    infos = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 80)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 80)),
    ]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: infos)
    with pytest.raises(UnsafeURL):
        linkpreview.public_addresses("mixed.test", 80)


def test_dns_rebinding_is_caught_at_connect_time(server, local_is_public, monkeypatch):
    """The address checked is the one connected to: there is no second lookup."""
    connected = []
    real_connect = socket.create_connection

    def spy(address, *a, **k):
        connected.append(address[0])
        return real_connect(address, *a, **k)

    monkeypatch.setattr(socket, "create_connection", spy)
    assert fetch_preview(_url(server, "/page"))["title"] == "OG & title"
    assert connected == ["127.0.0.1"]


def test_redirect_to_a_private_address_is_refused(server, monkeypatch):
    """The first hop is allowed; the redirect target is not."""
    other = HTTPServer(("127.0.0.2", 0), _Handler)
    other.hits = []
    threading.Thread(target=other.serve_forever, daemon=True).start()
    try:
        server.redirect_to = f"http://127.0.0.2:{other.server_port}/page"
        monkeypatch.setattr(linkpreview, "is_public_address", lambda a: a == "127.0.0.1")
        monkeypatch.setattr(
            linkpreview, "ALLOWED_PORTS", {80, 443, server.server_port, other.server_port}
        )
        assert fetch_preview(_url(server, "/redirect")) is None
        assert server.hits == ["/redirect"]
        assert other.hits == []
    finally:
        other.shutdown()


def test_redirect_to_a_bad_scheme_or_port_is_refused(server, local_is_public):
    server.redirect_to = "file:///etc/passwd"
    assert fetch_preview(_url(server, "/redirect")) is None
    server.redirect_to = "http://127.0.0.1:6379/"
    assert fetch_preview(_url(server, "/redirect")) is None


def test_redirect_within_public_hosts_is_followed(server, local_is_public):
    preview = fetch_preview(_url(server, "/redirect"))
    assert preview["title"] == "OG & title"
    assert preview["url"].endswith("/page")


def test_redirect_loop_ends(server, local_is_public):
    assert fetch_preview(_url(server, "/loop")) is None
    assert server.hits.count("/loop") == linkpreview.MAX_REDIRECTS + 1


def test_non_html_gives_no_preview(server, local_is_public):
    assert fetch_preview(_url(server, "/json")) is None


def test_read_stops_at_the_byte_cap(server, local_is_public, monkeypatch):
    monkeypatch.setattr(linkpreview, "MAX_BYTES", 1024)
    sizes = []
    real = linkpreview.parse_html

    def spy(html, url):
        sizes.append(len(html))
        return real(html, url)

    monkeypatch.setattr(linkpreview, "parse_html", spy)
    assert fetch_preview(_url(server, "/huge"))["title"] == "huge"
    assert sizes == [1024]


def test_a_server_that_drips_bytes_hits_the_total_deadline(server, local_is_public, monkeypatch):
    monkeypatch.setattr(linkpreview, "TOTAL_TIMEOUT", 0.5)
    monkeypatch.setattr(linkpreview, "MAX_BYTES", 200)  # ~10 s of dripping without a deadline
    started = time.monotonic()
    assert fetch_preview(_url(server, "/slow")) is None
    assert time.monotonic() - started < 3


def test_an_unknown_charset_falls_back_to_utf8(server, local_is_public):
    # Used to raise LookupError, failing the consumer until the event dead-lettered.
    assert fetch_preview(_url(server, "/badcharset"))["title"] == "OG & title"


def test_parser_cleans_and_caps_text():
    html = "<title>  a\n b </title><meta name=description content='" + "x" * 900 + "'>"
    preview = linkpreview.parse_html(html, "https://site.example/p")
    assert preview["title"] == "a b"
    assert len(preview["description"]) == 300
    assert preview["site"] == "site.example"
    assert linkpreview.parse_html("<p>no title</p>", "https://site.example/") is None


def test_first_url_drops_trailing_punctuation():
    assert first_url("see https://a.example/x, ok") == "https://a.example/x"
    assert first_url("راجع https://a.example/x؟") == "https://a.example/x"
    assert first_url("nothing here") is None


@pytest.mark.django_db
def test_refresh_stores_a_server_built_preview_and_clears_it(monkeypatch):
    calls = []

    def fake(url):
        calls.append(url)
        return {"url": url, "title": "T", "description": "", "site": "a.example"}

    monkeypatch.setattr(linkpreview, "fetch_preview", fake)
    author = str(uuid.uuid4())
    post = services.create_post(author, body="https://a.example/x")
    services.refresh_link_preview(str(post.id))
    services.refresh_link_preview(str(post.id))  # same URL: no second fetch
    post.refresh_from_db()
    assert post.link_preview["title"] == "T"
    assert calls == ["https://a.example/x"]

    services.edit_post(author, str(post.id), "no link now")
    services.refresh_link_preview(str(post.id))
    assert Post.objects.get(id=post.id).link_preview is None
