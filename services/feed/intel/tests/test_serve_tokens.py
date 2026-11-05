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
