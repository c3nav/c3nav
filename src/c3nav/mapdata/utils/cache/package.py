import os
import struct
from io import BytesIO
from pathlib import Path
from tarfile import TarFile, TarInfo
from typing import BinaryIO, Optional, Self, NamedTuple

from pyzstd import CParameter, ZstdError, ZstdFile

from c3nav.mapdata.utils.cache import AccessRestrictionAffected, GeometryIndexed, MapHistory

try:
    from asgiref.local import Local as LocalContext
except ImportError:
    from threading import local as LocalContext

ZSTD_MAGIC_NUMBER = b"\x28\xb5\x2f\xfd"


class CachePackageLevel(NamedTuple):
    history: MapHistory
    restrictions: AccessRestrictionAffected
    global_restrictions: frozenset[int]


class CachePackage:
    def __init__(self, bounds, levels=None):
        self.bounds = bounds
        self.levels = {} if levels is None else levels
        self.theme_ids = []

    def add_level(self, level_id: int, theme_id, history: MapHistory, restrictions: AccessRestrictionAffected,
                  level_restriction: int | None):
        self.levels[(level_id, theme_id)] = CachePackageLevel(
            history=history,
            restrictions=restrictions,
            global_restrictions=frozenset() if level_restriction is None else frozenset((level_restriction, ))
        )
        if theme_id not in self.theme_ids:
            self.theme_ids.append(theme_id)

    @staticmethod
    def get_filename(update_cache_key, compression=None):
        from django.conf import settings
        if compression is not None:
            return settings.CACHE_ROOT / update_cache_key / f'package.tar.{compression}'
        else:
            return settings.CACHE_ROOT / update_cache_key / 'package.tar'

    def save(self, update_cache_key, filename=None, compression=None):
        if filename is None:
            filename = self.get_filename(update_cache_key, compression=compression)

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
                    self._add_bytesio(f, 'global_restrictions_%s' % key,
                                      BytesIO(struct.pack('<B'+('I'*len(level_data.global_restrictions)),
                                                          len(level_data.global_restrictions),
                                                          *level_data.global_restrictions)))
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

    def save_all(self, update_cache_key, filename=None):
        for compression in (None, 'gz', 'xz', 'zst'):
            self.save(update_cache_key, filename, compression)

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
            global_restrictions_data = f.extractfile(files['global_restrictions_%s' % key]).read()
            levels[(level_id, theme_id)] = CachePackageLevel(
                history=MapHistory.read(f.extractfile(files['history_%s' % key])),
                restrictions=AccessRestrictionAffected.read(f.extractfile(files['restrictions_%s' % key])),
                global_restrictions=frozenset(
                    struct.unpack('<'+('I'*global_restrictions_data[0]), global_restrictions_data[1:])
                )
            )

        return cls(bounds, levels)

    @classmethod
    def open(cls, update_cache_key=None, package: Optional[str | os.PathLike] = None) -> Self:
        if package is None:
            if update_cache_key is None:
                raise ValueError
            package = cls.get_filename(update_cache_key)
        elif not hasattr(package, 'open'):
            package = Path(package)
        return cls.read(package.open('rb'))

    cached = LocalContext()

    @classmethod
    def open_cached(cls) -> Self:
        from c3nav.mapdata.models.update import MapUpdate, MapUpdateJob
        map_update = MapUpdateJob.last_successful_job("mapdata.recalculate_geometries")
        if getattr(cls.cached, 'key', None) != map_update:
            cls.cached.key = map_update
            cls.cached.data = None

        if cls.cached.data is None:
            cls.cached.data = cls.open(update_cache_key=map_update.cache_key)

        return cls.cached.data

    def bounds_valid(self, minx, miny, maxx, maxy):
        return (minx <= self.bounds[2] and maxx >= self.bounds[0] and
                miny <= self.bounds[3] and maxy >= self.bounds[1])
