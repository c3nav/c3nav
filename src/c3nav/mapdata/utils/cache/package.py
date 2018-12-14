import os
import struct
import threading
from collections import namedtuple
from io import BytesIO
from tarfile import TarFile, TarInfo

from c3nav.mapdata.utils.cache import AccessRestrictionAffected, GeometryIndexed, MapHistory

CachePackageLevel = namedtuple('CachePackageLevel', ('history', 'restrictions'))


class CachePackage:
    def __init__(self, bounds, levels=None):
        self.bounds = bounds
        self.levels = {} if levels is None else levels

    def add_level(self, level_id: int, history: MapHistory, restrictions: AccessRestrictionAffected):
        self.levels[level_id] = CachePackageLevel(history, restrictions)

    def save(self, filename=None, compression=None):
        if filename is None:
            from django.conf import settings
            filename = os.path.join(settings.CACHE_ROOT, 'package.tar')
            if compression is not None:
                filename += '.' + compression

        filemode = 'w'
        if compression is not None:
            filemode += ':' + compression

        with TarFile.open(filename, filemode) as f:
            self._add_bytesio(f, 'bounds', BytesIO(struct.pack('<iiii', *(int(i*100) for i in self.bounds))))

            for level_id, level_data in self.levels.items():
                self._add_geometryindexed(f, 'history_%d' % level_id, level_data.history)
                self._add_geometryindexed(f, 'restrictions_%d' % level_id, level_data.restrictions)

    def _add_bytesio(self, f: TarFile, filename: str, data: BytesIO):
        data.seek(0, os.SEEK_END)
        tarinfo = TarInfo(name=filename)
        tarinfo.size = data.tell()
        data.seek(0)
        f.addfile(tarinfo, data)

    def _add_geometryindexed(self, f: TarFile, filename: str, obj: GeometryIndexed):
        data = BytesIO()
        obj.write(data)
        self._add_bytesio(f, filename, data)

    def save_all(self, filename=None):
        for compression in (None, 'gz', 'xz'):
            self.save(filename, compression)

    @classmethod
    def read(cls, f):
        f = TarFile.open(fileobj=f)
        files = {info.name: info for info in f.getmembers()}

        bounds = tuple(i/100 for i in struct.unpack('<iiii', f.extractfile(files['bounds']).read()))

        levels = {}
        for filename in files:
            if not filename.startswith('history_'):
                continue
            level_id = int(filename[8:])
            levels[level_id] = CachePackageLevel(
                history=MapHistory.read(f.extractfile(files['history_%d' % level_id])),
                restrictions=AccessRestrictionAffected.read(f.extractfile(files['restrictions_%d' % level_id]))
            )

        return cls(bounds, levels)

    @classmethod
    def open(cls, filename=None):
        if filename is None:
            from django.conf import settings
            filename = os.path.join(settings.CACHE_ROOT, 'package.tar')
        return cls.read(open(filename, 'rb'))

    cached = None
    cache_key = None
    cache_lock = threading.Lock()

    @classmethod
    def open_cached(cls):
        with cls.cache_lock:
            from c3nav.mapdata.models import MapUpdate
            cache_key = MapUpdate.current_processed_cache_key()
            if cls.cache_key != cache_key:
                cls.cache_key = cache_key
                cls.cached = None

            if cls.cached is None:
                cls.cached = cls.open()

            return cls.cached

    def bounds_valid(self, minx, miny, maxx, maxy):
        return (minx <= self.bounds[2] and maxx >= self.bounds[0] and
                miny <= self.bounds[3] and maxy >= self.bounds[1])
