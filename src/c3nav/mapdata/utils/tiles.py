import base64
import hashlib
import hmac
import time

from c3nav.mapdata.utils.cache.compress import compress_sorted_list_of_int


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
    # todo: eventually use compress_sorted_list_of_int and decode it later?
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


def build_access_cache_key(access_permissions: set) -> tuple[str, str]:
    """
    return as readable and compressed
    todo: only do compressed?
    """
    sorted_permissions = sorted(access_permissions)
    return (
        ('-'.join(str(i) for i in sorted_permissions)) or '0',
        compress_sorted_list_of_int(sorted_permissions).decode(),
    )



def build_tile_etag(base_cache_key, access_cache_key, tile_secret):
    return '"' + base64.z85encode((f"{base_cache_key}:{access_cache_key}").encode()).decode() + '"'
