from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from tara_common import health

health.register_readiness_check("database", health.database_check())
health.register_readiness_check("cache", health.cache_check())

urlpatterns = [
    path("healthz/", health.liveness, name="liveness"),
    path("readyz/", health.readiness, name="readiness"),
    path("startupz/", health.readiness, name="startup"),
    path("", include("django_prometheus.urls")),
    path("api/v1/", include("notifications.urls")),
    path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/v1/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]
