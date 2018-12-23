from django.core.cache import cache


def increment_cache_key(cache_key):
    try:
        cache.incr(cache_key)
    except ValueError:
        cache.set(cache_key, 0, None)
