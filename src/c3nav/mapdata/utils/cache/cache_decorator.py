def mapdata_cache(func):
    cache_key = None
    cached_value = None

    def wrapper():
        nonlocal cached_value
        nonlocal cache_key
        from c3nav.mapdata.models import MapUpdate
        current_cache_key = MapUpdate.current_cache_key()
        if current_cache_key != cache_key:
            cached_value = func()
            cache_key = current_cache_key
        return cached_value

    return wrapper
