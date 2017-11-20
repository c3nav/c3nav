import base64
import logging
import os
import re
import time
from io import BytesIO

import requests

from c3nav.mapdata.utils.cache import CachePackage

logging.basicConfig(level=logging.DEBUG if os.environ.get('C3NAV_DEBUG') else logging.INFO,
                    format='[%(asctime)s] [%(process)s] [%(levelname)s] %(name)s: %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S %z')
logger = logging.getLogger('c3nav')


class TileServer:
    regex = re.compile(r'^/(?P<level>\d+)/(?P<zoom>\d+)/(?P<x>-?\d+)/(?P<y>-?\d+).png$')

    def __init__(self):
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

        self.auth_headers = {'X-Tile-Secret': base64.b64encode(self.tile_secret.encode())}

        self.cache_package = None
        self.cache_package_etag = None

        wait = 1
        while True:
            success = self.load_cache_package()
            if success:
                logger.info('Cache package successfully loaded.')
                break
            logger.info('Retrying after %s seconds...' % wait)
            time.sleep(wait)
            wait = min(2, wait*2)

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

        self.cache_package = CachePackage.read(BytesIO(r.content))
        self.cache_package_etag = r.headers.get('ETag', None)
        return True

    def not_found(self, start_response, text):
        start_response('404 Not Found', [('Content-Type', 'text/plain')])
        return [text]

    def __call__(self, env, start_response):
        match = self.regex.match(env['PATH_INFO'])
        if match is None:
            return self.not_found(start_response, b'invalid tile path.')

        zoom = int(match.group('zoom'))
        if not (0 <= zoom <= 10):
            return self.not_found(start_response, b'zoom out of bounds.')

        # do this to be thread safe
        cache_package = self.cache_package  # noqa

        x = int(match.group('x'))  # noqa
        y = int(match.group('y'))  # noqa

        level = int(match.group('level'))  # noqa

        start_response('200 OK', [('Content-Type', 'text/plain')])
        return [b'mau?']


application = TileServer()
