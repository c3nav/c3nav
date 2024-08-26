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
            "fields": self.fields,
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


class CollectedChanges(BaseSchema):
    prev_reprs: dict[str, dict[int, str]] = {}
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


@dataclass
class CollectedChangesPrefetch:
    changes: CollectedChanges
    instances: dict[ObjectReference, Model]

    def apply(self):
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

