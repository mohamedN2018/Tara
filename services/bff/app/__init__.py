"""Tara BFF — a thin edge aggregator.

It verifies user access tokens locally (JWKS), shapes client responses, and
calls backend services behind timeouts + circuit breaking. It owns no data.
This is intentionally small in Phase 1: health probes + a JWKS-verified whoami
that demonstrates the cross-service degradation pattern. See ADR-008.
"""
