from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from marketplace.stats import COUNTERS

from tara_common import health
from tara_common.stats import InternalStatsView

health.register_readiness_check("database", health.database_check())
health.register_readiness_check("cache", health.cache_check())

urlpatterns = [
    path("healthz/", health.liveness, name="liveness"),
    path("readyz/", health.readiness, name="readiness"),
    path("startupz/", health.readiness, name="startup"),
    path("", include("django_prometheus.urls")),
    path("api/v1/", include("marketplace.urls")),
    # Not routed by the edge: admin's platform statistics poll (8.11).
    path("internal/v1/stats/", InternalStatsView.as_view(counters=COUNTERS)),
    path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/v1/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]
