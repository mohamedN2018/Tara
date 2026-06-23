"""Root URL configuration for the Identity service.

- /api/v1/...            business API (see identity.urls)
- /.well-known/jwks.json public keys for decentralized token verification
- /healthz /readyz       liveness / readiness probes
- /metrics               Prometheus metrics (django_prometheus)
- /admin/                Django admin (internal)
- /api/v1/schema|docs    OpenAPI schema + Swagger UI
"""

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from identity.views import JWKSView

from tara_common import health

health.register_readiness_check("database", health.database_check())
health.register_readiness_check("cache", health.cache_check())

urlpatterns = [
    # Probes (root level so the orchestrator hits them without versioning).
    path("healthz/", health.liveness, name="liveness"),
    path("readyz/", health.readiness, name="readiness"),
    path("startupz/", health.readiness, name="startup"),
    # Public keys for JWT verification by other services.
    path(".well-known/jwks.json", JWKSView.as_view(), name="jwks"),
    # Prometheus.
    path("", include("django_prometheus.urls")),
    # Admin.
    path("admin/", admin.site.urls),
    # API v1.
    path("api/v1/", include("identity.urls")),
    # OpenAPI.
    path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/v1/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
]
