"""Channel-layer group naming.

Channels group names allow only [A-Za-z0-9._-], so we use '.' (never ':') as the
separator. Clients are added to their own user group on connect; they join
conversation groups on subscribe.
"""

from __future__ import annotations


def user_group(account_id: str) -> str:
    return f"user.{account_id}"


def conversation_group(conversation_id: str) -> str:
    return f"conv.{conversation_id}"
