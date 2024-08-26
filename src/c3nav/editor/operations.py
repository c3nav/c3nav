import copy
import datetime
import json
from dataclasses import dataclass
from typing import TypeAlias, Any, Annotated, Literal, Union

from django.apps import apps
from django.core import serializers
from django.db.models import Model
from django.utils import timezone
from pydantic.config import ConfigDict
from pydantic.fields import Field
from pydantic.types import Discriminator

from c3nav.api.schema import BaseSchema
from c3nav.mapdata.fields import I18nField

FieldValuesDict: TypeAlias = dict[str, Any]


class ObjectReference(BaseSchema):
    model_config = ConfigDict(frozen=True)
    model: str
    id: int

    @classmethod
    def from_instance(cls, instance: Model):
        """
        This method will not convert the ID yet!
        """
        return cls(model=instance._meta.model_name, id=instance.pk)


class BaseOperation(BaseSchema):
    obj: ObjectReference
    datetime: Annotated[datetime.datetime, Field(default_factory=timezone.now)]

    def apply(self, values: FieldValuesDict, instance: Model) -> Model:
        raise NotImplementedError


class CreateObjectOperation(BaseOperation):
    type: Literal["create"] = "create"
    fields: FieldValuesDict

    def apply_create(self) -> Model:
        instance = list(serializers.deserialize("json", json.dumps([{
            "model": f"mapdata.{self.obj.model}",
            "pk": self.obj.id,
            "fields": self.fields,
        }])))[0]
        instance.save(save_m2m=False)
        return instance.object


class UpdateObjectOperation(BaseOperation):
    type: Literal["update"] = "update"
    fields: FieldValuesDict

    def apply(self, values: FieldValuesDict, instance: Model) -> Model:
        values.update(self.fields)
        instance = list(serializers.deserialize("json", json.dumps([{
            "model": f"mapdata.{self.obj.model}",
            "pk": self.obj.id,
            "fields": values,
        }])))[0]
        instance.save(save_m2m=False)
        return instance.object


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


class ChangedManyToMany(BaseSchema):
    cleared: bool = False
    added: list[str] = []
    removed: list[str] = []


class ChangedObject(BaseSchema):
    obj: ObjectReference
    titles: dict[str, str]
    created: bool = False
    deleted: bool = False
    fields: FieldValuesDict = {}
    m2m_changes: dict[str, ChangedManyToMany] = {}


class CollectedChanges(BaseSchema):
    prev_titles: dict[str, dict[int, dict[str, str]]] = {}
    prev_values: dict[str, dict[int, FieldValuesDict]] = {}
    operations: list[DatabaseOperation] = []

    def prefetch(self) -> "CollectedChangesPrefetch":
        ids_to_query: dict[str, set[int]] = {model_name: set(val.keys())
                                             for model_name, val in self.prev_values.items()}

        instances: dict[ObjectReference, Model] = {}
        for model_name, ids in ids_to_query.items():
            model = apps.get_model("mapdata", model_name)
            instances.update(dict((ObjectReference(model=model_name, id=instance.pk), instance)
                                  for instance in model.objects.filter(pk__in=ids)))

        return CollectedChangesPrefetch(changes=self, instances=instances)

    @property
    def changed_objects(self) -> list[ChangedObject]:
        objects = {}
        for operation in self.operations:
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
                        changed_object.fields[field_name] = {lang: val
                                                             for lang, val in field[field_name].update(value).items()}
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
        prev_values = copy.deepcopy(self.changes.prev_values)
        for operation in self.changes.operations:
            if isinstance(operation, CreateObjectOperation):
                self.instances[operation.obj] = operation.apply_create()
            else:
                in_prev_values = operation.obj.id in prev_values.get(operation.obj.model, {})
                if not in_prev_values:
                    print('WARN WARN WARN')
                values = prev_values.setdefault(operation.obj.model, {}).setdefault(operation.obj.id, {})
                try:
                    instance = self.instances[operation.obj]
                except KeyError:
                    if not in_prev_values:
                        instance = apps.get_model("mapdata", operation.obj.model).filter(pk=operation.obj.id).first()
                    else:
                        instance = None
                if instance is not None:
                    operation.apply(values=values, instance=instance)

