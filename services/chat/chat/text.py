"""Search normalisation for message text (Arabic-aware).

The normaliser lives in ``tara_common.text`` (roadmap D6); this module keeps the
``chat.text.normalize`` name used by the services and migration 0003. The same
function runs on stored bodies (``Message.body_norm``) and on queries, so
``احمد`` finds ``أحمد``.
"""

from __future__ import annotations

from tara_common.text import normalize_ar as normalize

__all__ = ["normalize"]
