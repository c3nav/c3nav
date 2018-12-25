from django.core.cache import cache
from django.utils import timezone


def increment_cache_key(cache_key):
    try:
        cache.incr(cache_key)
    except ValueError:
        cache.set(cache_key, 0, None)


def stats_snapshot(reset=True):
    last_now = cache.get('apistats_last_reset', '', None)
    now = timezone.now()
    results = {}
    for key in cache.keys('apistats__*'):
        results[key] = cache.get(key)
        if reset:
            cache.delete(key)
    if reset:
        cache.set('apistats_last_reset', now, None)
    results = dict(sorted(results.items()))
    return {
        'start_time': str(last_now),
        'end_time': str(now),
        'data': results
    }
