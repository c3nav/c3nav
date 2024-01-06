import os
import struct
from collections import namedtuple
from io import BytesIO
from pathlib import Path
from tarfile import TarFile, TarInfo
from typing import BinaryIO, Optional, Self

from pyzstd import CParameter, ZstdError, ZstdFile

from c3nav.mapdata.utils.cache import AccessRestrictionAffected, GeometryIndexed, MapHistory

try:
    from asgiref.local import Local as LocalContext
except ImportError:
    from threading import local as LocalContext

ZSTD_MAGIC_NUMBER = b"\x28\xb5\x2f\xfd"
CachePackageLevel = namedtuple('CachePackageLevel', ('history', 'restrictions'))


class CachePackage:
    def __init__(self, bounds, levels=None):
        self.bounds = bounds
        self.levels = {} if levels is None else levels
        self.theme_ids = []

    def add_level(self, level_id: int, theme_id, history: MapHistory, restrictions: AccessRestrictionAffected):
        self.levels[(level_id, theme_id)] = CachePackageLevel(history, restrictions)
        if theme_id not in self.theme_ids:
            self.theme_ids.append(theme_id)

    def save(self, filename=None, compression=None):
        if filename is None:
            from django.conf import settings
            if compression is not None:
                filename = settings.CACHE_ROOT / f'package.tar.{compression}'
            else:
                filename = settings.CACHE_ROOT / 'package.tar'

        filemode = 'w'
        fileobj = None
        if compression == 'zst':
            fileobj = ZstdFile(filename, filemode, level_or_option={
                CParameter.compressionLevel: 9,
                CParameter.checksumFlag: 1,
            })
        elif compression is not None:
            filemode += ':' + compression

        try:
            with TarFile.open(filename, filemode, fileobj=fileobj) as f:
                self._add_bytesio(f, 'bounds',
                                  BytesIO(struct.pack('<iiii', *(int(i*100) for i in self.bounds))))

                for (level_id, theme_id), level_data in self.levels.items():
                    if theme_id is None:
                        key = '%d' % level_id
                    else:
                        key = '%d_%d' % (level_id, theme_id)
                    self._add_geometryindexed(f, 'history_%s' % key, level_data.history)
                    self._add_geometryindexed(f, 'restrictions_%s' % key, level_data.restrictions)
        finally:
            if fileobj is not None:
                fileobj.close()

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
        for compression in (None, 'gz', 'xz', 'zst'):
            self.save(filename, compression)

    @classmethod
    def read(cls, f: BinaryIO) -> Self:
        # test if it's a zstd compressed archive
        # read magic bytes
        magic_number = f.read(4)
        f.seek(0)
        if magic_number == ZSTD_MAGIC_NUMBER:
            # Seams to be a zstd file. To make sure we try to read the first 512 bytes.
            _f = f
            try:
                f = ZstdFile(f, 'rb')
                f.read(512)  # tar block size
                f.seek(0)
            except ZstdError:
                # Not a zst file or a broken file. Let's give Tarfile a try with the original file
                f = _f

        f = TarFile.open(fileobj=f)
        files = {info.name: info for info in f.getmembers()}

        bounds = tuple(i/100 for i in struct.unpack('<iiii', f.extractfile(files['bounds']).read()))

        levels = {}
        for filename in files:
            if not filename.startswith('history_'):
                continue
            key = filename[8:]
            if '_' in key:
                [level_id, theme_id] = [int(x) for x in key.split('_', 1)]
            else:
                level_id = int(key)
                theme_id = None
            levels[(level_id, theme_id)] = CachePackageLevel(
                history=MapHistory.read(f.extractfile(files['history_%s' % key])),
                restrictions=AccessRestrictionAffected.read(f.extractfile(files['restrictions_%s' % key]))
            )

        return cls(bounds, levels)

    @classmethod
    def open(cls, package: Optional[str | os.PathLike] = None) -> Self:
        if package is None:
            from django.conf import settings
            package = settings.CACHE_ROOT / 'package.tar'
        elif not hasattr(package, 'open'):
            package = Path(package)
        return cls.read(package.open('rb'))

    cached = LocalContext()

    @classmethod
    def open_cached(cls) -> Self:
        from c3nav.mapdata.models import MapUpdate
        cache_key = MapUpdate.current_processed_cache_key()
        if getattr(cls.cached, 'key', None) != cache_key:
            cls.cached.key = cache_key
            cls.cached.data = None

        if cls.cached.data is None:
            cls.cached.data = cls.open()

        return cls.cached.data

    def bounds_valid(self, minx, miny, maxx, maxy):
        return (minx <= self.bounds[2] and maxx >= self.bounds[0] and
                miny <= self.bounds[3] and maxy >= self.bounds[1])
