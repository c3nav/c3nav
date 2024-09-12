import copy
import datetime
import json
from dataclasses import dataclass
from typing import TypeAlias, Any, Annotated, Literal, Union
from uuid import UUID, uuid4

from django.apps import apps
from django.core import serializers
from django.db.models import Model
from django.utils import timezone
from pydantic.config import ConfigDict
from pydantic.fields import Field
from pydantic.types import Discriminator

from c3nav.api.schema import BaseSchema
from c3nav.mapdata.fields import I18nField
from c3nav.mapdata.models import LocationSlug

FieldValuesDict: TypeAlias = dict[str, Any]


class ObjectReference(BaseSchema):
    model_config = ConfigDict(frozen=True)
    model: str
    id: int

    @classmethod
    def from_instance(cls, instance: Model):
        return cls(model=instance._meta.model_name, id=instance.pk)


class PreviousObject(BaseSchema):
    titles: dict[str, str] | None
    values: FieldValuesDict


class PreviousObjects(BaseSchema):
    objects: dict[str, dict[int, PreviousObject]] = {}

    def get(self, ref: ObjectReference) -> PreviousObject | None:
        return self.objects.get(ref.model, {}).get(ref.id, None)

    def set(self, ref: ObjectReference, values: FieldValuesDict, titles: dict | None):
        self.objects.setdefault(ref.model, {})[ref.id] = PreviousObject(
            values=values,
            titles=titles,
        )

    def get_ids(self) -> dict[str, set[int]]:
        return {model: set(objs.keys()) for model, objs in self.objects.items()}


class BaseOperation(BaseSchema):
    obj: ObjectReference
    uuid: UUID = Field(default_factory=uuid4)
    datetime: Annotated[datetime.datetime, Field(default_factory=timezone.now)]

    def apply(self, values: FieldValuesDict, instance: Model) -> Model:
        raise NotImplementedError


class CreateObjectOperation(BaseOperation):
    type: Literal["create"] = "create"
    fields: FieldValuesDict

    def apply_create(self) -> Model:
        model = apps.get_model('mapdata', self.obj.model)
        data = []
        if issubclass(model, LocationSlug):
            data.append({
                "model": f"mapdata.locationslug",
                "pk": self.obj.id,
                "fields": {
                    "slug": self.fields.get("slug", None)
                },
            })
            values = {key: val for key, val in self.fields.items() if key != "slug"}
        else:
            values = self.fields
        data.append({
            "model": f"mapdata.{self.obj.model}",
            "pk": self.obj.id,
            "fields": values,
        })
        instances = list(serializers.deserialize("json", json.dumps(data)))
        for instance in instances:
            instance.save(save_m2m=False)
        return instances[-1].object


class UpdateObjectOperation(BaseOperation):
    type: Literal["update"] = "update"
    fields: FieldValuesDict

    def apply(self, values: FieldValuesDict, instance: Model) -> Model:
        model = apps.get_model('mapdata', self.obj.model)
        for field_name, value in self.fields.items():
            field = model._meta.get_field(field_name)
            if isinstance(field, I18nField) and field_name in self.fields:
                values[field_name] = {lang: val for lang, val in {**values[field_name], **value}.items()
                                      if val is not None}
            else:
                values[field_name] = value
        data = []
        if issubclass(model, LocationSlug) and "slug" in values:
            data.append({
                "model": f"mapdata.locationslug",
                "pk": self.obj.id,
                "fields": {
                    "slug": values["slug"],
                },
            })
            values = {key: val for key, val in values.items() if key != "slug"}
        data.append({
            "model": f"mapdata.{self.obj.model}",
            "pk": self.obj.id,
            "fields": values,
        })
        instances = list(serializers.deserialize("json", json.dumps(data)))
        for instance in instances:
            instance.save(save_m2m=False)
        return instances[-1].object


class DeleteObjectOperation(BaseOperation):
    type: Literal["delete"] = "delete"

    def apply(self, values: FieldValuesDict, instance: Model) -> Model:
        instance.delete()
        return instance


class UpdateManyToManyOperation(BaseOperation):
    type: Literal["m2m_add"] = "m2m_update"
    field: str
    add_values: set[int] = set()
    remove_values: set[int] = set()

    def apply(self, values: FieldValuesDict, instance: Model) -> Model:
        values[self.field] = sorted((set(values[self.field]) | self.add_values) - self.remove_values)
        field_manager = getattr(instance, self.field)
        field_manager.add(*self.add_values)
        field_manager.remove(*self.remove_values)
        return instance


class ClearManyToManyOperation(BaseOperation):
    type: Literal["m2m_clear"] = "m2m_clear"
    field: str

    def apply(self, values: FieldValuesDict, instance: Model) -> Model:
        values[self.field] = []
        getattr(instance, self.field).clear()
        return instance


class RevertOperation(BaseOperation):
    type: Literal["revert"] = "revert"
    reverts: UUID


DatabaseOperation = Annotated[
    Union[
        CreateObjectOperation,
        UpdateObjectOperation,
        DeleteObjectOperation,
        UpdateManyToManyOperation,
        ClearManyToManyOperation,
    ],
    Discriminator("type"),
]


class ChangedManyToMany(BaseSchema):
    cleared: bool = False
    added: list[str] = []
    removed: list[str] = []


class ChangedObject(BaseSchema):
    obj: ObjectReference
    titles: dict[str, str] | None
    created: bool = False
    deleted: bool = False
    fields: FieldValuesDict = {}
    m2m_changes: dict[str, ChangedManyToMany] = {}


class CollectedChanges(BaseSchema):
    uuid: UUID = Field(default_factory=uuid4)
    prev: PreviousObjects = PreviousObjects()
    operations: list[DatabaseOperation] = []

    def prefetch(self) -> "CollectedChangesPrefetch":
        ids_to_query: dict[str, set[int]] = self.prev.get_ids()

        instances: dict[ObjectReference, Model] = {}
        for model_name, ids in ids_to_query.items():
            model = apps.get_model("mapdata", model_name)
            instances.update(dict((ObjectReference(model=model_name, id=instance.pk), instance)
                                  for instance in model.objects.filter(pk__in=ids)))

        return CollectedChangesPrefetch(changes=self, instances=instances)

    @property
    def changed_objects(self) -> list[ChangedObject]:
        objects = {}
        reverted_uuids = frozenset(operation.reverts for operation in self.operationsy
                                   if isinstance(operation, RevertOperation))
        for operation in self.operations:
            if operation.uuid in reverted_uuids:
                continue
            changed_object = objects.get(operation.obj, None)
            if changed_object is None:
                changed_object = ChangedObject(obj=operation.obj,
                                               titles=self.prev_titles[operation.obj.model][operation.obj.id])
                objects[operation.obj] = changed_object
            if isinstance(operation, CreateObjectOperation):
                changed_object.created = True
                changed_object.fields.update(operation.fields)
            elif isinstance(operation, UpdateObjectOperation):
                model = apps.get_model('mapdata', operation.obj.model)
                for field_name, value in operation.fields.items():
                    field = model._meta.get_field(field_name)
                    if isinstance(field, I18nField) and field_name in changed_object.fields:
                        changed_object.fields[field_name] = {
                            lang: val for lang, val in {**changed_object.fields[field_name], **value}.items()
                        }
                    else:
                        changed_object.fields[field_name] = value
            elif isinstance(operation, DeleteObjectOperation):
                changed_object.deleted = False
            else:
                changed_m2m = changed_object.m2m_changes.get(operation.field, None)
                if changed_m2m is None:
                    changed_m2m = ChangedManyToMany()
                    changed_object.m2m_changes[operation.field] = changed_m2m
                if isinstance(operation, ClearManyToManyOperation):
                    changed_m2m.cleared = True
                    changed_m2m.added = []
                    changed_m2m.removed = []
                else:
                    changed_m2m.added = sorted((set(changed_m2m.added) | operation.add_values)
                                               - operation.remove_values)
                    changed_m2m.removed = sorted((set(changed_m2m.removed) - operation.add_values)
                                                 | operation.remove_values)
        return list(objects.values())


@dataclass
class CollectedChangesPrefetch:
    changes: CollectedChanges
    instances: dict[ObjectReference, Model]

    def apply(self):
        # todo: what if unique constraint error occurs?
        for operation in self.changes.operations:
            if isinstance(operation, CreateObjectOperation):
                self.instances[operation.obj] = operation.apply_create()
            else:
                prev_obj = self.changes.prev.get(operation.obj)
                if prev_obj is None:
                    print('WARN WARN WARN')
                values = prev_obj.values
                try:
                    instance = self.instances[operation.obj]
                except KeyError:
                    if prev_obj is None:
                        instance = apps.get_model("mapdata", operation.obj.model).filter(pk=operation.obj.id).first()
                    else:
                        instance = None
                if instance is not None:
                    operation.apply(values=values, instance=instance)

