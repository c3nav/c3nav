from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache

from c3nav.mapdata.models.report import Report

if settings.METRCIS:
    from prometheus_client import Gauge
    from prometheus_client.core import REGISTRY, CounterMetricFamily
    from prometheus_client.registry import Collector

    users_total = Gauge('c3nav_users_total', 'Total number of users')
    users_total.set_function(lambda: get_user_model().objects.count())
    reports_total = Gauge('c3nav_reports_total', 'Total number of reports')
    reports_total.set_function(lambda: Report.objects.count())
    reports_open = Gauge('c3nav_reports_open', 'Number of open reports')
    reports_open.set_function(lambda: Report.objects.filter(open=True).count()),

    class APIStatsCollector(Collector):
        def collect(self):
            if settings.CACHES['default']['BACKEND'] == 'django.core.cache.backends.redis.RedisCache':
                client = cache._cache.get_client()
                for key in client.keys(f"*{settings.CACHES['default'].get('KEY_PREFIX', '')}apistats__*"):
                    key = key.decode('utf-8').split(':', 2)[2]
                    yield CounterMetricFamily(f'c3nav_{key}', key, value=cache.get(key))

        def describe(self):
            return list()

    REGISTRY.register(APIStatsCollector())
