import base64
import hashlib
import hmac
import time

from django.conf import settings
from django.core.cache import cache

from c3nav.mapdata.models import Level, MapUpdate
from c3nav.mapdata.models.access import AccessPermission


def get_render_level_ids(cache_key=None):
    if cache_key is None:
        cache_key = MapUpdate.current_cache_key()
    cache_key = 'mapdata:render-level-ids:'+cache_key
    levels = cache.get(cache_key, None)
    if levels is None:
        levels = set(Level.objects.values_list('pk', flat=True))
        cache.set(cache_key, levels, 300)
    return levels


def set_tile_access_cookie(request, response):
    access_permissions = AccessPermission.get_for_request(request)

    if access_permissions:
        value = '-'.join(str(i) for i in access_permissions)+':'+str(int(time.time())+60)
        key = hashlib.sha1(settings.SECRET_TILE_KEY.encode()).digest()
        signed = base64.b64encode(hmac.new(key, msg=value.encode(), digestmod=hashlib.sha256).digest()).decode()
        response.set_cookie(settings.TILE_ACCESS_COOKIE_NAME, value+':'+signed, max_age=60)
    else:
        response.delete_cookie(settings.TILE_ACCESS_COOKIE_NAME)


def get_tile_access_cookie(request):
    try:
        cookie = request.COOKIES[settings.TILE_ACCESS_COOKIE_NAME]
    except KeyError:
        return set()

    try:
        access_permissions, expire, signed = cookie.split(':')
    except ValueError:
        return set()

    value = access_permissions+':'+expire

    key = hashlib.sha1(settings.SECRET_TILE_KEY.encode()).digest()
    signed_verify = base64.b64encode(hmac.new(key, msg=value.encode(), digestmod=hashlib.sha256).digest()).decode()
    if signed != signed_verify:
        return set()

    if int(expire) < time.time():
        return set()

    return set(int(i) for i in access_permissions.split('-'))
