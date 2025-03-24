import base64
import binascii
import hashlib
import hmac
import time


def get_tile_bounds(zoom, x, y):
    size = 256 / 2 ** zoom
    minx = size * x
    miny = size * (-y - 1)
    maxx = minx + size
    maxy = miny + size

    # add one pixel so tiles can overlap to avoid rendering bugs in chrome or webkit
    maxx += size / 256
    miny -= size / 256
    return minx, miny, maxx, maxy


def build_tile_access_cookie(access_permissions, tile_secret):
    value = '-'.join(str(i) for i in access_permissions) + ':' + str(int(time.time()) + 60)
    key = hashlib.sha1(tile_secret.encode()).digest()
    signed = base64.b64encode(hmac.new(key, msg=value.encode(), digestmod=hashlib.sha256).digest()).decode()
    return value + ':' + signed


def parse_tile_access_cookie(cookie, tile_secret):
    try:
        access_permissions, expire, signed = cookie.split(':')
    except ValueError:
        return set()
    value = access_permissions + ':' + expire
    key = hashlib.sha1(tile_secret.encode()).digest()
    signed_verify = base64.b64encode(hmac.new(key, msg=value.encode(), digestmod=hashlib.sha256).digest()).decode()
    if signed != signed_verify:
        return set()
    if int(expire) < time.time():
        return set()
    return set(int(i) for i in access_permissions.split('-'))


def build_base_cache_key(last_update):
    return '%x-%x-%x' % last_update


def build_access_cache_key(access_permissions: set):
    return '-'.join(str(i) for i in sorted(access_permissions)) or '0'


def build_tile_etag(level_id, zoom, x, y, theme_id, base_cache_key, access_cache_key, tile_secret):
    # we want a short etag so HTTP 304 responses are tiny
    return '"' + binascii.b2a_base64(hashlib.sha256(
        ('%d-%d-%d-%d:%s:%s:%s:%s' %
         (level_id, zoom, x, y, str(theme_id), base_cache_key, access_cache_key, tile_secret[:26])).encode()
    ).digest()[:15], newline=False).decode() + '"'
