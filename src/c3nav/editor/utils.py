from dataclasses import dataclass

from c3nav.mapdata.models import Level, Space
from c3nav.mapdata.permissions import active_map_permissions


class DefaultEditUtils:
    @classmethod
    def from_obj(cls, obj):
        return cls()

    @property
    def can_access_child_base_mapdata(self):
        return active_map_permissions.all_base_mapdata

    @property
    def can_create(self):
        return self.can_access_child_base_mapdata

    @property
    def _geometry_url(self):
        return None

    @property
    def geometry_url(self):
        return self._geometry_url if self.can_access_child_base_mapdata else None


@dataclass
class LevelChildEditUtils(DefaultEditUtils):
    level: Level

    @classmethod
    def from_obj(cls, obj):
        return cls(obj.level)

    @property
    def _geometry_url(self):
        return '/api/v2/editor/geometries/level/' + str(self.level.primary_level_pk)  # todo: resolve correctly


@dataclass
class SpaceChildEditUtils(DefaultEditUtils):
    space: Space

    @classmethod
    def from_obj(cls, obj):
        return cls(obj.space)

    @property
    def can_access_child_base_mapdata(self):
        return (active_map_permissions.all_base_mapdata or
                self.space.base_mapdata_accessible or
                self.space.pk in active_map_permissions.spaces)

    @property
    def _geometry_url(self):
        return '/api/v2/editor/geometries/space/'+str(self.space.pk)  # todo: resolve correctly
