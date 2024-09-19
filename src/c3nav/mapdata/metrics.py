import re
from typing import Optional, Sequence

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache

from c3nav.mapdata.models.report import Report

if settings.METRICS:
    from prometheus_client import Gauge
    from prometheus_client.core import CounterMetricFamily
    from prometheus_client.registry import Collector, CollectorRegistry

    REGISTRY = CollectorRegistry(auto_describe=True)
    users_total = Gauge('c3nav_users_total', 'Total number of users', registry=REGISTRY)
    users_total.set_function(lambda: get_user_model().objects.count())
    reports_total = Gauge('c3nav_reports_total', 'Total number of reports', registry=REGISTRY)
    reports_total.set_function(lambda: Report.objects.count())
    reports_open = Gauge('c3nav_reports_open', 'Number of open reports', registry=REGISTRY)
    reports_open.set_function(lambda: Report.objects.filter(open=True).count()),

    class APIStatsCollector(Collector):

        name_registry: dict[str, None | Sequence[str]] = dict()

        def collect(self):
            metrics: dict[str, CounterMetricFamily] = dict()
            if settings.CACHES['default']['BACKEND'] == 'django.core.cache.backends.redis.RedisCache':
                client = cache._cache.get_client()
                for key in client.keys(f"*{settings.CACHES['default'].get('KEY_PREFIX', '')}apistats__*"):
                    key: str = key.decode('utf-8').split(':', 2)[2]
                    value = cache.get(key)
                    key = key[10:]  # trim apistats__ from the beginning

                    # some routing stats don't use double underscores to separate fields, workaround for now
                    if key.startswith('route_tuple_'):
                        key = re.sub(r'^route_tuple_(.*)_(.*)$', r'route_tuple__\1__\2', key)
                    if key.startswith('route_origin_') or key.startswith('route_destination_'):
                        key = re.sub(r'^route_(origin|destination)_(.*)$', r'route_\1__\2', key)

                    name, *labels = key.split('__')
                    try:
                        label_names = self.name_registry[name]
                    except KeyError:
                        continue

                    if label_names is None:
                        label_names = list()

                    if len(label_names) != len(labels):
                        raise ValueError('configured labels and number of extracted labels doesn\'t match.')

                    try:
                        counter = metrics[name]
                    except KeyError:
                        counter = metrics[name] = CounterMetricFamily(f'c3nav_{name}', f'c3nav_{name}',
                                                                      labels=label_names)
                    counter.add_metric(labels, value)
            return metrics.values()

        def describe(self):
            return list()

        @classmethod
        def add_stat(cls, name:str, label_names: Optional[str | Sequence[str]] = None):
            if isinstance(label_names, str):
                label_names = [label_names]
            if name in cls.name_registry and label_names != cls.name_registry[name]:
                raise KeyError(f'{name} already exists')
            cls.name_registry[name] = label_names


    REGISTRY.register(APIStatsCollector())
