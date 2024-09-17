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


class TileServer:
    def __init__(self):
        self.path_regex = re.compile(r'^/(\d+)/(-?\d+)/(-?\d+)/(-?\d+)(/(-?\d+))?.png$')

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
            time.sleep(self.reload_interval)
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

    def not_found(self, start_response, text):
        start_response('404 Not Found', [self.get_date_header(),
                                         ('Content-Type', 'text/plain'),
                                         ('Content-Length', str(len(text)))])
        return [text]

    def internal_server_error(self, start_response, text=b'internal server error'):
        start_response('500 Internal Server Error', [self.get_date_header(),
                                                     ('Content-Type', 'text/plain'),
                                                     ('Content-Length', str(len(text)))])
        return [text]

    def deliver_tile(self, start_response, etag, data):
        start_response('200 OK', [self.get_date_header(),
                                  ('Content-Type', 'image/png'),
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

        match = self.path_regex.match(path_info)
        if match is None:
            return self.not_found(start_response, b'invalid tile path.')

        level, zoom, x, y, _, theme = match.groups()
        if theme is None:
            theme = 0

        zoom = int(zoom)
        if not (-2 <= zoom <= 5):
            return self.not_found(start_response, b'zoom out of bounds.')

        # do this to be thread safe
        try:
            cache_package = self.get_cache_package()
        except Exception as e:
            logger.error('get_cache_package() failed: %s' % e)
            return self.internal_server_error(start_response)

        # check if bounds are valid
        x = int(x)
        y = int(y)
        minx, miny, maxx, maxy = get_tile_bounds(zoom, x, y)
        if not cache_package.bounds_valid(minx, miny, maxx, maxy):
            return self.not_found(start_response, b'coordinates out of bounds.')

        # get level
        level = int(level)
        theme_id = int(theme)
        theme = None if theme_id == 0 else theme_id
        level_data = cache_package.levels.get((level, theme))
        if level_data is None:
            return self.not_found(start_response, b'invalid level or theme.')

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
        tile_etag = build_tile_etag(level, zoom, x, y, theme_id, base_cache_key, access_cache_key, self.tile_secret)
        if if_none_match == tile_etag:
            start_response('304 Not Modified', [self.get_date_header(),
                                                ('Content-Length', '0'),
                                                ('ETag', tile_etag)])
            return [b'']

        cache_key = path_info+'_'+tile_etag
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            return self.deliver_tile(start_response, tile_etag, cached_result)

        r = requests.get('%s/map/%d/%d/%d/%d/%d/%s.png' %
                         (self.upstream_base, level, zoom, x, y, theme_id, access_cache_key),
                         headers=self.auth_headers, auth=self.http_auth)
        if r.status_code == 200 and r.headers['Content-Type'] == 'image/png':
            if r.headers['ETag'] != tile_etag:
                error = b'outdated tile from upstream'
                start_response('503 Service Unavailable', [self.get_date_header(),
                                                           ('Content-Length', len(error)),
                                                           ('ETag', tile_etag)])
                return [error]
            self.cache.set(cache_key, r.content)
            return self.deliver_tile(start_response, tile_etag, r.content)

        start_response('%d %s' % (r.status_code, r.reason), [
            self.get_date_header(),
            ('Content-Length', str(len(r.content))),
            ('Content-Type', r.headers.get('Content-Type', 'text/plain'))
        ])
        return [r.content]


application = TileServer()
