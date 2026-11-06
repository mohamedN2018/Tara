"""WP 4c.2-B3: ``GET /api/v1/feed/delivery/``: the delivery blocks of Home, Reels and
Video for the web (reels and video pages, impressions outside Home). The same for
every viewer: no per-viewer data and no config version label; privately cacheable."""

import json
import uuid

import pytest
from django.urls import reverse
from intel import config

pytestmark = pytest.mark.django_db
URL = "/api/v1/feed/delivery/"


def test_the_route():
    assert reverse("feed:delivery") == URL


def test_it_returns_the_three_blocks_exactly_as_configured(client_for):
    resp = client_for(str(uuid.uuid4())).get(URL)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"data"}
    assert body["data"] == {s: config.delivery_for(s) for s in ("home", "reels", "video")}
    assert body["data"]["reels"]["first_page_size"] == 5
    assert resp["Cache-Control"] == "private, max-age=300"


def test_no_viewer_data_and_no_version_label(client_for):
    a = client_for(str(uuid.uuid4())).get(URL).json()
    b = client_for(str(uuid.uuid4())).get(URL).json()
    assert a == b
    text = json.dumps(a)
    assert "@" not in text and 'version"' not in text.replace('def_version"', "")


def test_authentication_is_required():
    from rest_framework.test import APIClient

    assert APIClient().get(URL).status_code in (401, 403)
