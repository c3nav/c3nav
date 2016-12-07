import os
import pickle
from contextlib import contextmanager

from django.conf import settings
from django.utils import timezone

last_mapdata_update_filename = os.path.join(settings.DATA_DIR, 'last_mapdata_update')
last_mapdata_update_decorator_depth = 0


def get_last_mapdata_update(default_now=False):
    try:
        with open(last_mapdata_update_filename, 'rb') as f:
            return pickle.load(f)
    except:
        return timezone.now() if default_now else None


@contextmanager
def set_last_mapdata_update():
    global last_mapdata_update_decorator_depth
    if last_mapdata_update_decorator_depth == 0:
        try:
            os.remove(last_mapdata_update_filename)
        except:
            pass
    last_mapdata_update_decorator_depth += 1
    yield
    last_mapdata_update_decorator_depth -= 1
    if last_mapdata_update_decorator_depth == 0:
        with open(last_mapdata_update_filename, 'wb') as f:
            pickle.dump(timezone.now(), f)
