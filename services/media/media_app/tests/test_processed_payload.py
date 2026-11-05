"""Tara Intelligence WP 2.6b: ``media.processed`` carries ``has_audio`` and ``fps``.

Both come from the probe stored when the video was prepared. They are optional
in the schema, so an event recorded before this change (or a probe that lacks
them) still validates, and nothing is guessed when the probe is silent.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import jsonschema
import pytest

from media_app import transcode
from media_app.models import MediaAsset, MediaVariant, OutboxEvent

pytestmark = pytest.mark.django_db

SCHEMA = Path("/opt/tara/libs/tara_events/tara_events/schemas/media.processed.v1.json")


@pytest.fixture(autouse=True)
def _keep_originals(settings):
    """No bucket in these tests: finalize must not try to delete the original."""
    settings.MEDIA_KEEP_VIDEO_ORIGINALS = True


def _schema() -> dict:
    if not SCHEMA.exists():
        pytest.skip("schemas are copied into the image at /opt/tara/libs")
    return json.loads(SCHEMA.read_text())


def _processing(probe: dict | None) -> MediaAsset:
    owner = uuid.uuid4()
    meta = {"rungs": [240, 360]}
    if probe is not None:
        meta["probe"] = probe
    asset = MediaAsset.objects.create(
        owner_id=owner,
        kind="video",
        purpose="post",
        mime="video/mp4",
        storage_key=f"videos/{owner}/{uuid.uuid4()}",
        status=MediaAsset.Status.PROCESSING,
        duration_ms=3000,
        video_meta=meta,
    )
    for w, h in ((426, 240), (640, 360)):
        MediaVariant.objects.create(
            media=asset, kind="hls", storage_key=f"{asset.storage_key}/hls/{h}", width=w, height=h
        )
    return asset


def _payload(asset: MediaAsset) -> dict:
    row = OutboxEvent.objects.get(event_type="media.processed", payload__subject_id=str(asset.id))
    return row.payload["payload"]


def _validate(payload: dict) -> None:
    jsonschema.validate(payload, _schema(), format_checker=jsonschema.FormatChecker())


def test_new_video_events_carry_has_audio_and_fps():
    asset = _processing(
        {"duration": 3.0, "width": 640, "height": 360, "fps": 29.97, "has_audio": True}
    )
    transcode.finalize(str(asset.id))
    payload = _payload(asset)
    assert payload["has_audio"] is True
    assert payload["fps"] == pytest.approx(29.97)
    _validate(payload)


def test_a_silent_clip_says_so():
    asset = _processing({"fps": 25, "has_audio": False})
    transcode.finalize(str(asset.id))
    payload = _payload(asset)
    assert payload["has_audio"] is False and payload["fps"] == 25.0
    _validate(payload)


@pytest.mark.parametrize("probe", [None, {}, {"fps": None, "has_audio": "yes"}, {"fps": -1}])
def test_nothing_is_guessed_when_the_probe_is_silent(probe):
    asset = _processing(probe)
    transcode.finalize(str(asset.id))
    payload = _payload(asset)
    assert "has_audio" not in payload and "fps" not in payload
    _validate(payload)


def test_an_event_recorded_before_the_change_still_validates():
    _validate(
        {
            "owner": str(uuid.uuid4()),
            "kind": "video",
            "variants": ["hls", "poster"],
            "purpose": "post",
            "renditions": [240, 360],
            "duration_ms": 3000,
            "width": 640,
            "height": 360,
        }
    )
    _validate({"owner": str(uuid.uuid4()), "kind": "image", "variants": ["thumb"]})


def test_the_schema_refuses_wrong_types():
    base = {"owner": str(uuid.uuid4()), "kind": "video", "variants": ["hls"]}
    for bad in ({"has_audio": "true"}, {"fps": -2}, {"fps": "30"}):
        with pytest.raises(jsonschema.ValidationError):
            _validate({**base, **bad})
