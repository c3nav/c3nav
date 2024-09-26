import datetime
import json
from dataclasses import dataclass
from typing import Annotated, Literal, Union, TypeAlias, Any
from uuid import UUID, uuid4

from django.apps import apps
from django.core import serializers
from django.db.models import Model
from django.utils import timezone
from pydantic import ConfigDict
from pydantic.fields import Field
from pydantic.types import Discriminator

from c3nav.api.schema import BaseSchema
from c3nav.mapdata.fields import I18nField
from c3nav.mapdata.models import LocationSlug


FieldValuesDict: TypeAlias = dict[str, Any]


class ObjectReference(BaseSchema):
    """
    Reference to an object based on model name and ID.
    """
    model_config = ConfigDict(frozen=True)
    model: str
    id: int

    @classmethod
    def from_instance(cls, instance: Model):
        return cls(model=instance._meta.model_name, id=instance.pk)


class PreviousObject(BaseSchema):
    """
    Represents the previous state of an objects, consisting of its values and its (multi-language) titles
    """
    titles: dict[str, str] | None
    values: FieldValuesDict


class PreviousObjectCollection(BaseSchema):
    objects: dict[str, dict[int, PreviousObject]] = {}

    def get(self, ref: ObjectReference) -> PreviousObject | None:
        return self.objects.get(ref.model, {}).get(ref.id, None)

    def get_ids(self) -> dict[str, set[int]]:
        """
        :return: all referenced IDs sorted by model
        """
        return {model: set(objs.keys()) for model, objs in self.objects.items()}

    def get_instances(self) -> dict[ObjectReference, Model]:
        """
        :return: all reference objects as fetched from the databse right now
        """
        instances: dict[ObjectReference, Model] = {}
        for model_name, ids in self.get_ids().items():
            model = apps.get_model("mapdata", model_name)
            instances.update(dict((ObjectReference(model=model_name, id=instance.pk), instance)
                                  for instance in model.objects.filter(pk__in=ids)))
        return instances

    def set(self, ref: ObjectReference, values: FieldValuesDict, titles: dict | None):
        self.objects.setdefault(ref.model, {})[ref.id] = PreviousObject(
            values=values,
            titles=titles,
        )


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


class DatabaseOperationCollection(BaseSchema):
    """
    A collection of database operations, sorted by model and id.
    Also stores a PreviousObjectCollection for comparison with the current state.
    Iterable as a list of DatabaseOperation instances.
    """
    prev: PreviousObjectCollection = PreviousObjectCollection()
    operations: list[DatabaseOperation] = []

    def __iter__(self):
        yield from self.operations

    def prefetch(self) -> "PrefetchedDatabaseOperationCollection":
        return PrefetchedDatabaseOperationCollection(operations=self, instances=self.prev.get_instances())


@dataclass
class PrefetchedDatabaseOperationCollection:
    operations: DatabaseOperationCollection
    instances: dict[ObjectReference, Model]

    def apply(self):
        # todo: what if unique constraint error occurs?
        for operation in self.operations.operations:
            if isinstance(operation, CreateObjectOperation):
                self.instances[operation.obj] = operation.apply_create()
            else:
                prev_obj = self.operations.prev.get(operation.obj)
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