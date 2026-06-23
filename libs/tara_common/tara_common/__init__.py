"""Tara shared kernel.

Deliberately thin: response/error envelope, cursor pagination, JWKS-based JWT
authentication, request-id middleware, and health probes. Everything here is
imported by every Tara service, so it must stay decoupled and dependency-light.
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
