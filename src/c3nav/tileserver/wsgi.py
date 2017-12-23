import base64
import logging
import os
import re
import threading
import time
from email.utils import formatdate
from io import BytesIO

import pylibmc
import requests

from c3nav.mapdata.utils.cache import CachePackage
from c3nav.mapdata.utils.tiles import (build_access_cache_key, build_base_cache_key, build_tile_etag, get_tile_bounds,
                                       parse_tile_access_cookie)

logging.basicConfig(level=logging.DEBUG if os.environ.get('C3NAV_DEBUG') else logging.INFO,
                    format='[%(asctime)s] [%(process)s] [%(levelname)s] %(name)s: %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S %z')
logger = logging.getLogger('c3nav')


class TileServer:
    def __init__(self):
        self.path_regex = re.compile(r'^/(\d+)/(-\d+)/(-?\d+)/(-?\d+).png$')

        self.cookie_regex = re.compile(r'(^| )c3nav_tile_access="?([^;" ]+)"?')

        try:
            self.upstream_base = os.environ['C3NAV_UPSTREAM_BASE'].strip('/')
        except KeyError:
            raise Exception('C3NAV_UPSTREAM_BASE needs to be set.')

        self.tile_secret = os.environ.get('C3NAV_TILE_SECRET', None)
        if not self.tile_secret:
            tile_secret_file = None
            try:
                tile_secret_file = os.environ['C3NAV_TILE_SECRET_FILE']
                self.tile_secret = open(tile_secret_file).read().strip()
            except KeyError:
                raise Exception('C3NAV_TILE_SECRET or C3NAV_TILE_SECRET_FILE need to be set.')
            except FileNotFoundError:
                raise Exception('The C3NAV_TILE_SECRET_FILE (%s) does not exist.' % tile_secret_file)

        self.reload_interval = int(os.environ.get('C3NAV_RELOAD_INTERVAL', 60))

        self.auth_headers = {'X-Tile-Secret': base64.b64encode(self.tile_secret.encode())}

        self.cache_package = None
        self.cache_package_etag = None

        self.date_header = ('Date', '0')
        threading.Thread(target=self.date_thread, daemon=True).start()

        self.tile_cache = pylibmc.Client(["127.0.0.1"], binary=True, behaviors={"tcp_nodelay": True, "ketama": True})

        wait = 1
        while True:
            success = self.load_cache_package()
            if success:
                logger.info('Cache package successfully loaded.')
                break
            logger.info('Retrying after %s seconds...' % wait)
            time.sleep(wait)
            wait = min(10, wait*2)

        threading.Thread(target=self.update_cache_package_thread, daemon=True).start()

    def update_cache_package_thread(self):
        while True:
            time.sleep(self.reload_interval)
            self.load_cache_package()

    def date_thread(self):
        # why do we do this in a thread? because it makes us able to handle 2000 requests per second more
        while True:
            now = time.time()
            self.date_header = 'Date', formatdate(timeval=time.time(), localtime=False, usegmt=True)
            time.sleep(1-(now-int(now)))

    def load_cache_package(self):
        logger.debug('Downloading cache package from upstream...')
        try:
            headers = self.auth_headers.copy()
            if self.cache_package_etag is not None:
                headers['If-None-Match'] = self.cache_package_etag
            r = requests.get(self.upstream_base+'/map/cache/package.tar.xz', headers=headers)

            if r.status_code == 403:
                logger.error('Rejected cache package download with Error 403. Tile secret is probably incorrect.')
                return False

            if r.status_code == 304:
                if self.cache_package is not None:
                    logger.debug('Not modified.')
                    return True
                logger.error('Unexpected not modified.')
                return False

            r.raise_for_status()
        except Exception as e:
            logger.error('Cache package download failed: %s' % e)
            return False

        try:
            self.cache_package = CachePackage.read(BytesIO(r.content))
            self.cache_package_etag = r.headers.get('ETag', None)
        except Exception as e:
            logger.error('Cache package parsing failed: %s' % e)
            return False
        return True

    def not_found(self, start_response, text):
        start_response('404 Not Found', [self.date_header,
                                         ('Content-Type', 'text/plain'),
                                         ('Content-Length', str(len(text)))])
        return [text]

    def deliver_tile(self, start_response, etag, data):
        start_response('200 OK', [self.date_header,
                                  ('Content-Type', 'image/png'),
                                  ('Content-Length', str(len(data))),
                                  ('Cache-Control', 'no-cache'),
                                  ('ETag', etag)])
        return [data]

    def __call__(self, env, start_response):
        match = self.path_regex.match(env['PATH_INFO'])
        if match is None:
            return self.not_found(start_response, b'invalid tile path.')

        level, zoom, x, y = match.groups()

        zoom = int(zoom)
        if not (-2 <= zoom <= 5):
            return self.not_found(start_response, b'zoom out of bounds.')

        # do this to be thread safe
        cache_package = self.cache_package

        # check if bounds are valid
        x = int(x)
        y = int(y)
        minx, miny, maxx, maxy = get_tile_bounds(zoom, x, y)
        if not cache_package.bounds_valid(minx, miny, maxx, maxy):
            return self.not_found(start_response, b'coordinates out of bounds.')

        # get level
        level = int(level)
        level_data = cache_package.levels.get(level)
        if level_data is None:
            return self.not_found(start_response, b'invalid level.')

        # build cache keys
        last_update = level_data.history.last_update(minx, miny, maxx, maxy)
        base_cache_key = build_base_cache_key(last_update)

        # decode access permissions
        access_permissions = set()
        access_cache_key = '0'

        cookie = env.get('HTTP_COOKIE', None)
        if cookie:
            cookie = self.cookie_regex.search(cookie)
            if cookie:
                cookie = cookie.group(2)
                access_permissions = (parse_tile_access_cookie(cookie, self.tile_secret) &
                                      set(level_data.restrictions[minx:maxx, miny:maxy]))
                access_cache_key = build_access_cache_key(access_permissions)

        # check browser cache
        if_none_match = env.get('HTTP_IF_NONE_MATCH')
        tile_etag = build_tile_etag(level, zoom, x, y, base_cache_key, access_cache_key, self.tile_secret)
        if if_none_match == tile_etag:
            start_response('304 Not Modified', [self.date_header,
                                                ('Content-Length', '0'),
                                                ('ETag', tile_etag)])
            return [b'']

        cached_result = self.tile_cache.get(tile_etag)
        if cached_result is not None:
            return self.deliver_tile(start_response, tile_etag, cached_result)

        r = requests.get('%s/map/%d/%d/%d/%d/%s.png' % (self.upstream_base, level, zoom, x, y, access_cache_key),
                         headers=self.auth_headers)

        if r.status_code == 200 and r.headers['Content-Type'] == 'image/png':
            self.tile_cache[tile_etag] = r.content
            return self.deliver_tile(start_response, tile_etag, r.content)

        start_response('%d %s' % (r.status_code, r.reason), [self.date_header,
                                                             ('Content-Length', len(r.content)),
                                                             ('Content-Type', r.headers['Content-Type'])])
        return [r.content]


application = TileServer()
