"""Rate-limit settings. Imported from settings.py, so it must not import DRF."""

from __future__ import annotations

import os

# Trusted proxies in front of the service, so a client cannot pick its own
# rate-limit bucket by sending X-Forwarded-For.
NUM_PROXIES = int(os.getenv("TARA_NUM_PROXIES", "1"))


def api_throttling() -> dict:
    """Keys to merge into a service's ``REST_FRAMEWORK`` setting."""
    return {
        "NUM_PROXIES": NUM_PROXIES,
        "DEFAULT_THROTTLE_CLASSES": [
            "tara_common.throttling.ReadThrottle",
            "tara_common.throttling.WriteThrottle",
        ],
        "DEFAULT_THROTTLE_RATES": {
            "tara_read": os.getenv("TARA_READ_RATE", "600/min"),
            "tara_write": os.getenv("TARA_WRITE_RATE", "120/min"),
        },
    }
