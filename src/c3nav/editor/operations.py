import json
from contextlib import suppress
from dataclasses import dataclass
from typing import Annotated, Literal, Union, TypeAlias, Any, Self, Iterator

from django.apps import apps
from django.core import serializers
from django.db.models import Model
from pydantic import ConfigDict
from pydantic.types import Discriminator

from c3nav.api.schema import BaseSchema
from c3nav.mapdata.fields import I18nField

ModelName: TypeAlias = str
ObjectID: TypeAlias = int
FieldName: TypeAlias = str

FieldValuesDict: TypeAlias = dict[FieldName, Any]


class ObjectReference(BaseSchema):
    """
    Reference to an object based on model name and ID.
    """
    model_config = ConfigDict(frozen=True)
    model: ModelName
    id: ObjectID

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
    objects: dict[ModelName, dict[ObjectID, PreviousObject]] = {}

    def get(self, ref: ObjectReference) -> PreviousObject | None:
        return self.objects.get(ref.model, {}).get(ref.id, None)

    def get_ids(self) -> dict[ModelName, set[ObjectID]]:
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

    def add_other(self, other: Self):
        for key in set(self.objects.keys()) | set(other.objects.keys()):
            self.objects[key] = {**other.objects.get(key, {}), **self.objects.get(key, {})}


class BaseOperation(BaseSchema):
    obj: ObjectReference

    def apply(self, values: FieldValuesDict, instance: Model) -> Model:
        raise NotImplementedError


class CreateObjectOperation(BaseOperation):
    type: Literal["create"] = "create"
    fields: FieldValuesDict

    def get_data(self):
        return [{
            "model": f"mapdata.{self.obj.model}",
            "pk": self.obj.id,
            "fields": self.fields,
        }]

    def apply_create(self) -> dict[ObjectReference, Model]:
        data = self.get_data()
        instances = [item.object for item in serializers.deserialize("json", json.dumps(data))]
        for instance in instances:
            # .object. to make sure our own .save() function is called!
            instance.save()
        return {self.obj: instances[-1]}


class CreateMultipleObjectsOperation(BaseSchema):
    type: Literal["create_multiple"] = "create_multiple"
    objects: list[CreateObjectOperation] = []

    def apply_create(self) -> dict[ObjectReference, Model]:
        indexes = {}
        data = []
        for obj in self.objects:
            data.extend(obj.get_data())
            indexes[obj.obj] = len(data)-1
        instances = [item.object for item in serializers.deserialize("json", json.dumps(data))]
        if hasattr(instances[-1], "pre_save_changed_geometries"):
            for instance in instances:
                instance.pre_save_changed_geometries()
        model = apps.get_model('mapdata', self.objects[0].obj.model)
        model.objects.bulk_create(instances)
        return {ref: instances[i] for ref, i in indexes.items()}


# todo: delete multiple objects


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
        data = [{
            "model": f"mapdata.{self.obj.model}",
            "pk": self.obj.id,
            "fields": values,
        }]
        instances = list(serializers.deserialize("json", json.dumps(data)))
        for i in instances:
            new_instance = i.object
            if hasattr(instance, "_orig") and not hasattr(new_instance, "_orig"):
                new_instance._orig = instance._orig
            if hasattr(instance, "_orig_geometry") and not hasattr(new_instance, "_orig_geometry"):
                new_instance._orig_geometry = instance._orig_geometry
            new_instance.save()
        return instances[-1].object


class DeleteObjectOperation(BaseOperation):
    type: Literal["delete"] = "delete"

    def apply(self, values: FieldValuesDict, instance: Model) -> Model:
        instance.delete()
        return instance


class UpdateManyToManyOperation(BaseOperation):
    type: Literal["m2m_update"] = "m2m_update"
    field: FieldName
    add_values: set[ObjectID] = set()
    remove_values: set[ObjectID] = set()

    def apply(self, values: FieldValuesDict, instance: Model) -> Model:
        values[self.field] = sorted((set(values[self.field]) | self.add_values) - self.remove_values)
        field_manager = getattr(instance, self.field)
        field_manager.add(*self.add_values)
        field_manager.remove(*self.remove_values)
        with suppress(AttributeError):
            instance.register_change(force=True)
        return instance


class ClearManyToManyOperation(BaseOperation):
    type: Literal["m2m_clear"] = "m2m_clear"
    field: FieldName

    def apply(self, values: FieldValuesDict, instance: Model) -> Model:
        values[self.field] = []
        getattr(instance, self.field).clear()
        with suppress(AttributeError):
            instance.register_change(force=True)
        return instance


DatabaseOperation = Annotated[
    Union[
        CreateObjectOperation,
        CreateMultipleObjectsOperation,
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

    def __iter__(self) -> Iterator[DatabaseOperation]:
        yield from self.operations

    def __len__(self):
        return len(self.operations)

    def extend(self, items: list[DatabaseOperation]):
        self.operations.extend(items)

    def append(self, item: DatabaseOperation):
        self.operations.append(item)

    def __getitem__(self, item):
        return self.operations[item]

    def prefetch(self) -> "PrefetchedDatabaseOperationCollection":
        return PrefetchedDatabaseOperationCollection(operations=self, instances=self.prev.get_instances())


@dataclass
class PrefetchedDatabaseOperationCollection:
    operations: DatabaseOperationCollection
    instances: dict[ObjectReference, Model]

    def apply(self):
        # todo: what if unique constraint error occurs?
        prev = self.operations.prev.model_copy(deep=True)
        for operation in self.operations:
            if isinstance(operation, (CreateObjectOperation, CreateMultipleObjectsOperation)):
                self.instances.update(operation.apply_create())
                sub_ops = operation.objects if isinstance(operation, CreateMultipleObjectsOperation) else [operation]
                for sub_op in sub_ops:
                    prev.set(ref=sub_op.obj, values=sub_op.fields, titles=None)

            else:
                prev_obj = prev.get(operation.obj)
                if prev_obj is None:
                    raise ValueError(f'Missing: {operation.obj}')
                try:
                    instance = self.instances[operation.obj]
                except KeyError:
                    if prev_obj is None:
                        instance = apps.get_model("mapdata", operation.obj.model).filter(pk=operation.obj.id).first()
                    else:
                        instance = None
                if instance is None:
                    raise ValueError('Instance to update doesn\'t exist')
                operation.apply(values=prev_obj.values, instance=instance)