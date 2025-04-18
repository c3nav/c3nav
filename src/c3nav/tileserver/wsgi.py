import base64
import logging
import os
import pickle
import re
import threading
import time
from datetime import datetime
from email.utils import formatdate
from io import BytesIO

import pylibmc
import requests
from pyzstd import decompress as zstd_decompress
from requests.auth import HTTPBasicAuth

from c3nav.mapdata.utils.cache import CachePackage
from c3nav.mapdata.utils.tiles import (build_access_cache_key, build_base_cache_key, build_tile_etag, get_tile_bounds,
                                       parse_tile_access_cookie)

loglevel = logging.DEBUG if os.environ.get('C3NAV_DEBUG', False) else os.environ.get('C3NAV_LOGLEVEL', 'INFO').upper()

logging.basicConfig(level=loglevel,
                    format='[%(asctime)s] [%(process)s] [%(levelname)s] %(name)s: %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S %z')

logger = logging.getLogger('c3nav')

if os.environ.get('C3NAV_LOGFILE'):
    logging.basicConfig(filename=os.environ['C3NAV_LOGFILE'])

type Headers = tuple[tuple[str, str], ...]


class TileServer:
    def __init__(self):
        self.path_regex = re.compile(r'^/(\d+)/(-?\d+)/(-?\d+)/(-?\d+)(/(-?\d+))?.(png|webp)$')

        self.cookie_regex = re.compile(r'(^| )c3nav_tile_access="?([^;" ]+)"?')

        try:
            self.upstream_base = os.environ['C3NAV_UPSTREAM_BASE'].strip('/')
        except KeyError:
            raise Exception('C3NAV_UPSTREAM_BASE needs to be set.')

        try:
            self.data_dir = os.environ.get('C3NAV_DATA_DIR', 'data')
        except KeyError:
            raise Exception('C3NAV_DATA_DIR needs to be set.')

        if not os.path.exists(self.data_dir):
            os.mkdir(self.data_dir)

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

        self.http_auth = os.environ.get('C3NAV_HTTP_AUTH', None)
        if self.http_auth:
            self.http_auth = HTTPBasicAuth(*self.http_auth.split(':', 1))

        self.auth_headers = {'X-Tile-Secret': base64.b64encode(self.tile_secret.encode()).decode()}

        self.processed_geometry_update = None
        self.cache_package = None
        self.cache_package_etag = None
        self.cache_package_filename = None

        cache = self.get_cache_client()

        wait = 1
        while True:
            success = self.load_cache_package(cache=cache)
            if success:
                logger.info('Cache package successfully loaded.')
                break
            logger.info('Retrying after %s seconds...' % wait)
            time.sleep(wait)
            wait = min(10, wait*2)

        threading.Thread(target=self.update_cache_package_thread, daemon=True).start()

    @staticmethod
    def get_cache_client():
        servers = os.environ.get('C3NAV_MEMCACHED_SERVER', '127.0.0.1').split(',')
        return pylibmc.Client(servers, binary=True, behaviors={"tcp_nodelay": True, "ketama": True})

    def update_cache_package_thread(self):
        cache = self.get_cache_client()  # different thread → different client!
        while True:
            # we try to make the reload happen predictably around the same time everywhere
            time.sleep(self.reload_interval - max((time.time() % self.reload_interval), self.reload_interval/2))
            self.load_cache_package(cache=cache)

    def get_date_header(self):
        return 'Date', formatdate(timeval=time.time(), localtime=False, usegmt=True)

    def load_cache_package(self, cache):
        logger.debug('Downloading cache package from upstream...')
        try:
            headers = self.auth_headers.copy()
            if self.cache_package_etag is not None:
                headers['If-None-Match'] = self.cache_package_etag
            r = requests.get(self.upstream_base+'/map/cache/package.tar.zst', headers=headers, auth=self.http_auth)

            if r.status_code == 403:
                logger.error('Rejected cache package download with Error 403. Tile secret is probably incorrect.')
                return False

            if r.status_code == 401:
                logger.error('Rejected cache package download with Error 401. You have HTTP Auth active.')
                return False

            if r.status_code == 304:
                if self.cache_package is not None:
                    logger.debug('Not modified.')
                    cache['cache_package_filename'] = self.cache_package_filename
                    cache.set('cache_package_last_successful_check', time.time())
                    return True
                logger.error('Unexpected not modified.')
                return False

            r.raise_for_status()
        except Exception as e:
            logger.error('Cache package download failed: %s' % e)
            return False

        logger.debug('Receiving and loading new cache package...')

        try:
            with BytesIO(zstd_decompress(r.content)) as f:
                self.cache_package = CachePackage.read(f)
            self.cache_package_etag = r.headers.get('ETag', None)
            self.processed_geometry_update = int(r.headers['X-Processed-Geometry-Update'])
        except Exception as e:
            logger.error('Cache package parsing failed: %s' % e)
            return False

        try:
            self.cache_package_filename = os.path.join(
                self.data_dir,
                datetime.now().strftime('%Y-%m-%d_%H-%M-%S-%f')+'.pickle'
            )
            with open(self.cache_package_filename, 'wb') as f:
                pickle.dump(self.cache_package, f)
            cache.set('cache_package_filename', self.cache_package_filename)
            cache.set('cache_package_last_successful_check', time.time())
        except Exception as e:
            self.cache_package_etag = None
            logger.error('Saving pickled package failed: %s' % e)
            return False
        return True

    def not_found(self, start_response, text, headers: Headers = ()):
        start_response('404 Not Found', [self.get_date_header(),
                                         ('Content-Type', 'text/plain'),
                                         ('Content-Length', str(len(text))),
                                         *headers])
        return [text]

    def service_unavailable(self, start_response, text=b'Service unavailable', headers: Headers = ()):
        start_response('503 Service Unavailable', [self.get_date_header(),
                                                   ('Content-Type', 'text/plain'),
                                                   ('Content-Length', str(len(text))),
                                                   *headers,])
        return [text]

    def no_content(self, start_response, headers):
        start_response('204 Not Modified', [self.get_date_header(),
                                            ('Content-Length', '0'),
                                            *headers, ])
        return [b'']

    def method_not_allowed(self, start_response, headers):
        start_response('405 Method Not Allowed', [self.get_date_header(),
                                                  ('Content-Length', '0'),
                                                  *headers, ])
        return [b'']

    def not_modified(self, start_response, tile_etag, headers):
        start_response('304 Not Modified', [self.get_date_header(),
                                            ('Content-Length', '0'),
                                            ('ETag', tile_etag),
                                            *headers, ])
        return [b'']

    def deliver_tile(self, start_response, etag, data, ext, headers: Headers = ()):
        start_response('200 OK', [self.get_date_header(),
                                  ('Content-Type', f'image/{ext}'),
                                  ('Content-Length', str(len(data))),
                                  ('Cache-Control', 'no-cache'),
                                  ('ETag', etag)])
        return [data]

    def liveness_check_response(self, start_response):
        self.get_cache_package()
        text = b'OK'
        start_response('200 OK', [self.get_date_header(),
                                  ('Content-Type', 'text/plain'),
                                  ('Content-Length', str(len(text)))])
        return [text]

    def readiness_check_response(self, start_response):
        text = b'OK'
        error = False
        try:
            last_check = self.cache.get('cache_package_last_successful_check')
        except pylibmc.Error:
            error = True
            text = b'memcached error'
        else:
            if last_check is None or last_check <= (time.time() - self.reload_interval * 3):
                error = True
                if last_check:
                    text = f'last successful cache package check was {time.time() - last_check}s ago.'.encode('utf-8')
                else:
                    text = b'last successful cache package check is unknown'
        start_response(('500 Internal Server Error' if error else '200 OK'),
                       [self.get_date_header(),
                        ('Content-Type', 'text/plain'),
                        ('Content-Length', str(len(text)))])
        return [text]

    def get_cache_package(self):
        try:
            cache_package_filename = self.cache.get('cache_package_filename')
        except pylibmc.Error as e:
            logger.warning('pylibmc error in get_cache_package(): %s' % e)
            cache_package_filename = None

        if cache_package_filename is None:
            logger.warning('cache_package_filename went missing.')
            return self.cache_package
        if self.cache_package_filename != cache_package_filename:
            logger.debug('Loading new cache package in worker.')
            self.cache_package_filename = cache_package_filename
            with open(self.cache_package_filename, 'rb') as f:
                self.cache_package = pickle.load(f)
        return self.cache_package

    @property
    def cache(self):
        cache = self.get_cache_client()
        self.__dict__['cache'] = cache
        return cache

    def __call__(self, env, start_response):
        path_info = env['PATH_INFO']

        if path_info == '/health' or path_info == '/health/live':
            return self.liveness_check_response(start_response)

        if path_info == '/health/ready':
            return self.readiness_check_response(start_response)

        origin_header = env.get("HTTP_ORIGIN", "null")
        cors_headers = []
        if origin_header != "null":
            cors_headers = (
                ('Access-Control-Allow-Origin', origin_header),
                ('Access-Control-Allow-Headers', 'If-none-match'),
                ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
            )

        if env["REQUEST_METHOD"] == "OPTIONS":
            return self.no_content(start_response, headers=cors_headers)
        elif env["REQUEST_METHOD"] != "GET":
            return self.method_not_allowed(start_response, headers=cors_headers)

        match = self.path_regex.match(path_info)
        if match is None:
            return self.not_found(start_response, b'invalid tile path.', headers=cors_headers)

        level, zoom, x, y, _, theme, ext = match.groups()
        if theme is None:
            theme = 0

        zoom = int(zoom)
        if not (-2 <= zoom <= 5):
            return self.not_found(start_response, b'zoom out of bounds.', headers=cors_headers)

        # do this to be thread safe
        try:
            cache_package = self.get_cache_package()
        except Exception as e:
            logger.error('get_cache_package() failed: %s' % e)
            return self.service_unavailable(start_response, b'upstream sync failed',
                                            headers=cors_headers)

        # check if bounds are valid
        x = int(x)
        y = int(y)
        minx, miny, maxx, maxy = get_tile_bounds(zoom, x, y)
        if not cache_package.bounds_valid(minx, miny, maxx, maxy):
            return self.not_found(start_response, b'coordinates out of bounds.', headers=cors_headers)

        # get level
        level = int(level)
        theme_id = int(theme)
        theme = None if theme_id == 0 else theme_id
        level_data = cache_package.levels.get((level, theme))
        if level_data is None:
            return self.not_found(start_response, b'invalid level or theme.', headers=cors_headers)

        # build cache keys
        last_update = level_data.history.last_update(minx, miny, maxx, maxy)
        base_cache_key = build_base_cache_key(last_update)

        # decode access permissions
        access_permissions = set()
        access_cache_key = '0'
        compressed_access_cache_key = '0'

        cookie = env.get('HTTP_COOKIE', None)
        if cookie:
            cookie = self.cookie_regex.search(cookie)
            if cookie:
                cookie = cookie.group(2)
                access_permissions = (
                    parse_tile_access_cookie(cookie, self.tile_secret) &
                    (set(level_data.restrictions[minx:maxx, miny:maxy]) | level_data.global_restrictions)
                )
                access_cache_key, compressed_access_cache_key = build_access_cache_key(access_permissions)

        if not all((r in access_permissions) for r in level_data.global_restrictions):
            return self.not_found(start_response, b'invalid level or theme.', headers=cors_headers)

        if cors_headers:
            cors_headers += (
                ('Access-Control-Expose-Headers', 'ETag'),
            )

        # check browser cache
        if_none_match = env.get('HTTP_IF_NONE_MATCH')
        tile_etag = build_tile_etag(base_cache_key, compressed_access_cache_key, self.tile_secret)
        if if_none_match == tile_etag:
            return self.not_modified(start_response, tile_etag, headers=cors_headers)

        cache_key = path_info+'_'+tile_etag
        try:
            cached_result = self.cache.get(cache_key)
        except pylibmc.Error as e:
            logger.error("Can't read tile from memcached: " + repr(cache_key))
            cached_result = None
        if cached_result is not None:
            return self.deliver_tile(start_response, tile_etag, cached_result, ext, headers=cors_headers)

        try:
            r = requests.get(f'{self.upstream_base}/map/{level}/{zoom}/{x}/{y}/{theme_id}/{access_cache_key}.{ext}',
                             headers=self.auth_headers, auth=self.http_auth, timeout=2)
        except requests.exceptions.Timeout:
            if if_none_match:
                # send 304, even though it's wrong. just display an old tile, sorry.
                return self.not_modified(start_response, tile_etag, headers=(*cors_headers, ('X-Timeout', 'true')))
            # sorry, can't help you right now.
            return self.service_unavailable(start_response, b'upstream timeout', headers=cors_headers)
        except ConnectionError:
            return self.service_unavailable(start_response, b'upstream fetch failed',
                                            headers=cors_headers)

        if r.status_code == 200 and r.headers['Content-Type'] == f'image/{ext}':
            if int(r.headers.get('X-Processed-Geometry-Update', 0)) < self.processed_geometry_update:
                return self.service_unavailable(start_response, b'upstream is outdated',
                                                headers=cors_headers)
            try:
                self.cache.set(cache_key, r.content)
            except pylibmc.Error as e:
                logger.error("Can't write tile to cache: " + repr(cache_key))

            return self.deliver_tile(start_response, tile_etag, r.content, ext, headers=cors_headers)

        start_response('%d %s' % (r.status_code, r.reason), [
            self.get_date_header(),
            ('Content-Length', str(len(r.content))),
            ('Content-Type', r.headers.get('Content-Type', 'text/plain')),
            *cors_headers,
        ])
        return [r.content]


application = TileServer()
