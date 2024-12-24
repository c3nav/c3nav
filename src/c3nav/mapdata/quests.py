from abc import abstractmethod
from dataclasses import dataclass
from itertools import chain
from typing import Self, Optional, Any, Type

from django.core.cache import cache
from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel
from pydantic.type_adapter import TypeAdapter
from shapely.geometry import Point, mapping

from c3nav.api.schema import BaseSchema, PointSchema
from c3nav.mapdata.models.access import AccessPermission
from c3nav.mapdata.models.geometry.space import RangingBeacon


@dataclass
class Quest:
    obj: Any

    @property
    @abstractmethod
    def point(self) -> dict:
        raise NotImplementedError

    @property
    def level_id(self) -> int:
        return self.obj.level_id

    @property
    def identifier(self) -> str:
        return str(self.obj.pk)

    @classmethod
    def _qs_for_request(cls, request):
        raise NotImplementedError

    @classmethod
    def _obj_to_quests(cls, obj) -> list[Self]:
        return [cls(obj=obj)]

    @classmethod
    def get_for_request(cls, request, identifier: Any) -> Optional[Self]:
        if not identifier.isdigit():
            return None
        results = list(chain(
            +(cls._obj_to_quests(obj) for obj in cls._qs_for_request(request).filter(pk=int(identifier)))
        ))
        if len(results) > 1:
            raise ValueError('wrong number of results')
        return results[0] if results else None

    @classmethod
    def get_all_for_request(cls, request) -> list[Self]:
        return list(chain(
            *(cls._obj_to_quests(obj) for obj in cls._qs_for_request(request))
        ))

    @classmethod
    def cached_get_all_for_request(cls, request) -> list["QuestSchema"]:
        cache_key = f'quests:{cls.identifier}:{AccessPermission.cache_key_for_request(request)}'
        result = cache.get(cache_key, None)
        if result is not None:
            return result
        adapter = TypeAdapter(list[QuestSchema])
        result = adapter.dump_python(adapter.validate_python(cls.get_all_for_request(request)))
        cache.set(cache_key, result, 900)
        return result


quest_types: dict[str, Type[BaseModel]] = {}


def register_quest(cls):
    quest_types[cls.quest_type] = cls
    return cls


@register_quest
@dataclass
class RangingBeaconAltitudeQuest(Quest):
    quest_type = "ranging_beacon_altitude"
    quest_type_label = _('Ranging Beacon Altitude')
    obj: RangingBeacon

    @property
    def point(self) -> Point:
        return mapping(self.obj.geometry)

    @classmethod
    def _qs_for_request(cls, request):
        return RangingBeacon.qs_for_request(request).select_related('space').filter(altitude_quest=True)


class QuestSchema(BaseSchema):
    quest_type: str
    identifier: str
    level_id: int
    point: PointSchema


def get_all_quests_for_request(request) -> list[QuestSchema]:
    return list(chain(*(
        quest.cached_get_all_for_request(request)
        for key, quest in quest_types.items()
        if request.user.is_superuser or key in request.user_permissions.quests
    )))
