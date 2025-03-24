from dataclasses import dataclass
from itertools import chain
from typing import Any, Self, Optional, Type

from django.core.cache import cache
from django.forms import ModelForm
from pydantic import TypeAdapter, BaseModel

from c3nav.api.schema import BaseSchema, PointSchema
from c3nav.editor.models import ChangeSet
from c3nav.editor.views.base import within_changeset
from c3nav.mapdata.models import MapUpdate

from c3nav.mapdata.models.access import AccessPermission
from c3nav.mapdata.permissions import active_map_permissions


@dataclass
class Quest:
    obj: Any

    @property
    def quest_description(self) -> list[str]:
        return []

    @property
    def point(self) -> dict:
        raise NotImplementedError

    @property
    def level_id(self) -> int:
        return self.obj.main_level_id

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
    def get_for_request(cls, request, identifier: str) -> Optional[Self]:
        if not identifier.isdigit():
            return None
        if not (request.user.is_superuser or cls.quest_type in request.user_permissions.quests):
            return None

        results = list(chain(
            *(cls._obj_to_quests(obj) for obj in cls._qs_for_request(request).filter(pk=int(identifier)))
        ))
        if len(results) > 1:
            raise ValueError('wrong number of results')
        return results[0] if results else None

    @classmethod
    def get_all_for_request(cls, request) -> list[Self]:
        if not (request.user.is_superuser or cls.quest_type in request.user_permissions.quests):
            return None
        return list(chain(
            *(cls._obj_to_quests(obj) for obj in cls._qs_for_request(request))
        ))

    @classmethod
    def cached_get_all_for_request(cls, request) -> list["QuestSchema"]:
        # todo: fix caching here
        cache_key = f'quests:{cls.quest_type}:{MapUpdate.last_update().cache_key}:{active_map_permissions.permissions_cache_key}'
        result = cache.get(cache_key, None)
        if result is not None:
            return result
        adapter = TypeAdapter(list[QuestSchema])
        result = adapter.dump_python(adapter.validate_python(cls.get_all_for_request(request)))
        cache.set(cache_key, result, 900)
        return result

    def get_form_class(self):
        return self.form_class

    def get_form_kwargs(self, request):
        return {"instance": self.obj}


class ChangeSetModelForm(ModelForm):
    def __init__(self, request, **kwargs):
        super().__init__(**kwargs)
        self.request = request

    @property
    def changeset_title(self):
        raise NotImplementedError

    def save(self, **kwargs):
        changeset = ChangeSet()
        changeset.author = self.request.user
        with within_changeset(changeset=changeset, user=self.request.user) as locked_changeset:
            super().save(**kwargs)
        with changeset.lock_to_edit() as locked_changeset:
            locked_changeset.title = self.changeset_title
            locked_changeset.description = 'quest'
            locked_changeset.apply(self.request.user)


quest_types: dict[str, Type[BaseModel]] = {}


def register_quest(cls):
    quest_types[cls.quest_type] = cls
    return cls


def get_quest_for_request(request, quest_type: str, identifier: str) -> Optional[Quest]:
    quest_cls = quest_types.get(quest_type, None)
    if quest_cls is None:
        return None
    return quest_cls.get_for_request(request, identifier)


class QuestSchema(BaseSchema):
    quest_type: str
    identifier: str
    level_id: int
    point: PointSchema


def get_all_quests_for_request(request, requested_quest_types: Optional[list[str]]) -> list[QuestSchema]:
    if requested_quest_types is None:
        return list(chain(*(
            quest.cached_get_all_for_request(request)
            for key, quest in quest_types.items()
            if request.user.is_superuser or key in request.user_permissions.quests
        )))
    else:
        return list(chain(*(
            quest.cached_get_all_for_request(request)
            for key, quest in quest_types.items()
            if key in requested_quest_types and (request.user.is_superuser or key in request.user_permissions.quests)
        )))