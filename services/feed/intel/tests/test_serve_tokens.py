"""WP 2.3: serve tokens (signature, expiry, viewer, secret separation) and Home's ``st``."""

import base64
import time
import uuid
from datetime import timedelta

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone
from feed.models import FeedItem

from intel.ranking import serve_tokens as st

from .helpers import acct

VIEWER, ITEM = acct(), acct()


def _issue(**kw):
    defaults = {
        "position": 3,
        "cfg_version": "home@1",
        "variant": "b",
        "source": "friend",
        "reason": "for_you",
    }
    defaults.update(kw)
    return st.issue(VIEWER, "post", ITEM, "home", **defaults)


def test_roundtrip_carries_every_claim():
    token = _issue(scores=st.quantize([0.0, 0.5, 1.0]))
    claims = st.verify(token, VIEWER, "post", ITEM)
    assert claims is not None
    assert (claims.surface, claims.position, claims.cfg_version, claims.variant) == (
        "home",
        3,
        "home@1",
        "b",
    )
    assert (claims.source, claims.reason) == ("friend", "for_you")
    assert list(claims.scores) == [0, 128, 255]
    assert len(token) <= 160  # about 120 bytes base64url (02 section 12.2)


def test_tampered_token_is_refused():
    raw = bytearray(base64.urlsafe_b64decode(_issue() + "=="))
    raw[20] ^= 0x01
    forged = base64.urlsafe_b64encode(bytes(raw)).rstrip(b"=").decode()
    assert st.verify(forged, VIEWER, "post", ITEM) is None
    assert st.verify("not-a-token", VIEWER, "post", ITEM) is None
    assert st.verify("", VIEWER, "post", ITEM) is None


def test_expiry_and_future_issue():
    now = time.time()
    token = _issue(now=now)
    assert st.verify(token, VIEWER, "post", ITEM, now=now + st.TTL_SECONDS - 1)
    assert st.verify(token, VIEWER, "post", ITEM, now=now + st.TTL_SECONDS + 1) is None
    future = _issue(now=now + st.MAX_FUTURE_SKEW_SECONDS + 60)
    assert st.verify(future, VIEWER, "post", ITEM, now=now) is None


def test_wrong_viewer_or_item_is_refused():
    token = _issue()
    assert st.verify(token, acct(), "post", ITEM) is None
    assert st.verify(token, VIEWER, "post", acct()) is None
    assert st.verify(token, VIEWER, "profile", ITEM) is None
    # A post, its reel and its video share the post id.
    assert st.verify(token, VIEWER, "video", ITEM) is not None


def test_secret_must_differ_from_secret_key_and_internal_secret(settings):
    token = _issue()
    settings.INTEL_SERVE_TOKEN_SECRET = settings.SECRET_KEY
    with pytest.raises(ImproperlyConfigured):
        _issue()
    settings.INTEL_SERVE_TOKEN_SECRET = settings.TARA_INTERNAL_JWT_SECRET
    with pytest.raises(ImproperlyConfigured):
        st.verify(token, VIEWER, "post", ITEM)


def test_token_signed_with_another_secret_is_refused(settings):
    token = _issue()
    settings.INTEL_SERVE_TOKEN_SECRET = "another-secret-another-secret-another-secret"
    assert st.verify(token, VIEWER, "post", ITEM) is None


def test_dev_key_is_not_secret_key(settings):
    settings.INTEL_SERVE_TOKEN_SECRET = ""
    assert st._key() != settings.SECRET_KEY.encode()
    assert st.verify(_issue(), VIEWER, "post", ITEM) is not None


def test_production_needs_the_secret(settings):
    settings.INTEL_SERVE_TOKEN_SECRET = ""
    settings.TARA_ENV = "production"
    with pytest.raises(ImproperlyConfigured):
        _issue()


# ---- Home items carry st ---------------------------------------------------------


def _feed_row(viewer, minutes_ago=0, reason="friend"):
    post_id, author = str(uuid.uuid4()), acct()
    return FeedItem.objects.create(
        recipient_id=viewer,
        post_id=post_id,
        author_id=author,
        reason=reason,
        snapshot={"post_id": post_id, "author_id": author, "audience": "public", "excerpt": "x"},
        post_created_at=timezone.now() - timedelta(minutes=minutes_ago),
    )


@pytest.mark.django_db
def test_for_you_items_carry_attributing_tokens(client_for):
    viewer = acct()
    rows = [_feed_row(viewer, minutes_ago=m) for m in range(5)]
    body = client_for(viewer).get("/api/v1/feed/?mode=for_you&limit=3").json()
    items = body["data"]
    assert len(items) == 3
    for pos, item in enumerate(items):
        claims = st.verify(item["st"], viewer, "post", item["post_id"])
        assert claims is not None
        assert (claims.surface, claims.position, claims.cfg_version) == ("home", pos, "home@1")
        assert claims.source == "friend" and claims.reason == "for_you"
        # Nobody else can spend it.
        assert st.verify(item["st"], acct(), "post", item["post_id"]) is None
    page2 = (
        client_for(viewer)
        .get(f"/api/v1/feed/?mode=for_you&limit=3&cursor={body['page']['next_cursor']}")
        .json()["data"]
    )
    assert [st.decode(i["st"]).position for i in page2] == [3, 4]
    assert {i["post_id"] for i in items + page2} == {str(r.post_id) for r in rows}


@pytest.mark.django_db
def test_chronological_items_carry_tokens_without_config(client_for):
    viewer = acct()
    _feed_row(viewer)
    item = client_for(viewer).get("/api/v1/feed/?mode=recent").json()["data"][0]
    claims = st.verify(item["st"], viewer, "post", item["post_id"])
    assert claims.surface == "home" and claims.reason == "recent"
    assert claims.cfg_version is None and claims.position is None


# ---- R3 WP 4b.16: serve token v2 ---------------------------------------------------------


def test_v2_carries_format_topic_length_author_and_visit():
    author = uuid.uuid4()
    token = _issue(fmt="image", topic_id=513, length_bucket=2, author_id=author, visit_ord=37)
    claims = st.verify(token, VIEWER, "post", ITEM)
    assert claims.version == 2
    assert (claims.fmt, claims.topic_id, claims.length_bucket) == ("image", 513, 2)
    assert claims.author_prefix == author.bytes[:8]
    assert claims.visit_ord == 37 % 32
    assert len(token) <= 180


def test_v1_tokens_keep_validating_until_they_expire():
    now = time.time()
    v1 = _issue(version=1, now=now)
    claims = st.verify(v1, VIEWER, "post", ITEM, now=now + 60)
    assert claims is not None and claims.version == 1
    assert (claims.fmt, claims.length_bucket, claims.author_prefix, claims.visit_ord) == (
        None,
        None,
        None,
        None,
    )
    assert claims.cfg_version == "home@1" and claims.position == 3
    assert st.verify(v1, VIEWER, "post", ITEM, now=now + st.TTL_SECONDS + 1) is None
    with pytest.raises(ValueError):
        _issue(version=3)


def test_v2_extension_is_signed():
    raw = bytearray(base64.urlsafe_b64decode(_issue(fmt="text", length_bucket=1) + "=="))
    raw[-17] ^= 0x01  # the visit byte, just before the MAC
    forged = base64.urlsafe_b64encode(bytes(raw)).rstrip(b"=").decode()
    assert st.verify(forged, VIEWER, "post", ITEM) is None
    # A v1 body relabelled as v2 (or the reverse) no longer parses.
    raw = bytearray(base64.urlsafe_b64decode(_issue(version=1) + "=="))
    raw[0] = 2
    assert st.decode(base64.urlsafe_b64encode(bytes(raw)).rstrip(b"=").decode()) is None


def test_length_bucket_follows_the_config_buckets():
    buckets = [{"max_chars": 10, "scale": 0.5}, {"max_chars": 100, "scale": 1.0}]
    assert st.length_bucket(None, buckets) == 0
    assert st.length_bucket("x" * 10, buckets) == 1
    assert st.length_bucket("x" * 11, buckets) == 2
    assert st.length_bucket("x" * 1000, buckets) == 2
    assert st.length_bucket("x", []) == 0


@pytest.mark.django_db
def test_stamp_home_items_v2_from_the_served_snapshot():
    from intel import config

    viewer, author = acct(), str(uuid.uuid4())
    buckets = config.for_surface("home").get("exposure.length_buckets")
    items = [
        {
            "post_id": str(uuid.uuid4()),
            "author_id": author,
            "reason": "friend",
            "snapshot": {"type": "image", "excerpt": "x" * 5},
        },
        # Content stripped for this viewer: no excerpt, so the bucket is unknown.
        {
            "post_id": str(uuid.uuid4()),
            "author_id": author,
            "reason": "friend",
            "snapshot": {"type": "reel"},
        },
    ]
    st.stamp_home_items(viewer, items, "for_you", offset=0, ranked=True, visit_ord=5)
    first = st.verify(items[0]["st"], viewer, "post", items[0]["post_id"])
    second = st.verify(items[1]["st"], viewer, "post", items[1]["post_id"])
    assert (first.fmt, first.length_bucket, first.visit_ord) == (
        "image",
        st.length_bucket("x" * 5, buckets),
        5,
    )
    assert first.author_prefix == uuid.UUID(author).bytes[:8]
    assert (second.fmt, second.length_bucket) == ("reel", 0)
    # Callers that pass no visit (Track A passes it) get 0.
    st.stamp_home_items(viewer, items, "recent", offset=None, ranked=False)
    assert st.decode(items[0]["st"]).visit_ord == 0
