import os

from django.conf import settings

from c3nav.celery import app


@app.task()
def delete_old_cached_tiles(*args, **kwargs):
    from c3nav.mapdata.models import MapUpdate
    cache_key = MapUpdate.current_cache_key()

    for folder in os.listdir(settings.TILES_ROOT):
        if folder == cache_key:
            continue
        fullpath = os.path.join(settings.TILES_ROOT, folder)
        if os.path.isdir(fullpath):
            os.system('rm -rf '+fullpath)
