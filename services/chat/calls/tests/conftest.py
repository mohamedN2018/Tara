import pytest

KEY = "test-key"
SECRET = "test-secret-for-calls-0123456789abcdef"


class FakeLiveKit:
    """Records server API calls instead of reaching a LiveKit server."""

    def __init__(self) -> None:
        self.removed: list[tuple[str, str]] = []
        self.deleted: list[str] = []
        self.rooms: dict[str, list[str]] = {}
        self.down = False

    def remove_participant(self, room: str, identity: str) -> None:
        self.removed.append((room, identity))

    def delete_room(self, room: str) -> None:
        self.deleted.append(room)

    def room_identities(self, room: str):
        from calls.livekit import LiveKitUnavailable

        if self.down:
            raise LiveKitUnavailable("list_participants")
        return self.rooms.get(room)


@pytest.fixture(autouse=True)
def livekit_on(settings):
    settings.LIVEKIT_API_KEY = KEY
    settings.LIVEKIT_API_SECRET = SECRET
    settings.LIVEKIT_URL = "ws://livekit.test"
    settings.LIVEKIT_INTERNAL_URL = "http://livekit.test:7880"
    settings.CALL_RING_TIMEOUT_SECONDS = 45
    settings.CALL_MAX_PARTICIPANTS = 16
    settings.CALL_START_RATE = "1000/min"
    return settings


@pytest.fixture(autouse=True)
def lk(monkeypatch):
    fake = FakeLiveKit()
    monkeypatch.setattr("calls.livekit.remove_participant", fake.remove_participant)
    monkeypatch.setattr("calls.livekit.delete_room", fake.delete_room)
    monkeypatch.setattr("calls.livekit.room_identities", fake.room_identities)
    return fake
