from itertools import chain
from typing import Type, Any, Optional, Annotated, Union

from django.apps import apps
from django.db.models import Model, OneToOneField, ForeignKey
from pydantic.config import ConfigDict

from c3nav.api.schema import BaseSchema
from c3nav.editor.operations import DatabaseOperationCollection, CreateObjectOperation, UpdateObjectOperation, \
    DeleteObjectOperation, ClearManyToManyOperation, FieldValuesDict, ObjectReference, PreviousObjectCollection, \
    DatabaseOperation
from c3nav.mapdata.fields import I18nField


class ChangedManyToMany(BaseSchema):
    cleared: bool = False
    added: list[int] = []
    removed: list[int] = []


class ChangedObject(BaseSchema):
    obj: ObjectReference
    titles: dict[str, str] | None
    created: bool = False
    deleted: bool = False
    fields: FieldValuesDict = {}
    m2m_changes: dict[str, ChangedManyToMany] = {}


class OperationDependencyObjectExists(BaseSchema):
    obj: ObjectReference
    nullable: bool


class OperationDependencyUniqueValue(BaseSchema):
    model_config = ConfigDict(frozen=True)

    model: str
    field: str
    value: Any
    nullable: bool


class OperationDependencyNoProtectedReference(BaseSchema):
    model_config = ConfigDict(frozen=True)

    obj: ObjectReference


OperationDependency = Union[
    OperationDependencyObjectExists,
    OperationDependencyNoProtectedReference,
    OperationDependencyUniqueValue,
]


class SingleOperationWithDependencies(BaseSchema):
    operation: DatabaseOperation
    dependencies: set[OperationDependency] = set()


class MergableOperationsWithDependencies(BaseSchema):
    children: list[SingleOperationWithDependencies]


OperationWithDependencies = Union[
    SingleOperationWithDependencies,
    MergableOperationsWithDependencies,
]


class DummyValue:
    pass


class ChangedObjectCollection(BaseSchema):
    """
    A collection of ChangedObject instances, sorted by model and id.
    Also stores a PreviousObjectCollection for comparison with the current state.
    Iterable as a list of ChangedObject instances.
    """
    prev: PreviousObjectCollection = PreviousObjectCollection()
    objects: dict[str, dict[int, ChangedObject]] = {}

    def __iter__(self):
        yield from chain(*(objects.values() for model, objects in self.objects.items()))

    def __len__(self):
        return sum(len(v) for v in self.objects.values())

    def add_operations(self, operations: DatabaseOperationCollection):
        """
        Add the given operations, creating/updating changed objects to represent the resulting state.
        """
        # todo: if something is being changed back, remove it from thingy?
        self.prev.add_other(operations.prev)
        for operation in operations:
            changed_object = self.objects.setdefault(operation.obj.model, {}).get(operation.obj.id, None)
            if changed_object is None:
                changed_object = ChangedObject(obj=operation.obj,
                                               titles=self.prev.get(operation.obj).titles)
                self.objects[operation.obj.model][operation.obj.id] = changed_object
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

    def clean_and_complete_prev(self):
        ids: dict[str, set[int]] = {}
        for model_name, changed_objects in self.objects.items():
            ids.setdefault(model_name, set()).update(set(changed_objects.keys()))
            model = apps.get_model("mapdata", model_name)
            relations: dict[str, Type[Model]] = {field.name: field.related_model
                                                 for field in model.get_fields() if field.is_relation}
            for obj in changed_objects.values():
                for field_name, value in obj.fields.items():
                    related_model = relations.get(field_name, None)
                    if related_model is None or value is None:
                        continue
                    ids.setdefault(related_model._meta.model_name, set()).add(value)
                for field_name, field_changes in obj.m2m_changes.items():
                    related_model = relations[field_name]
                    if field_changes.added or field_changes.removed:
                        ids.setdefault(related_model._meta.model_name, set()).update(field_changes.added)
                        ids.setdefault(related_model._meta.model_name, set()).update(field_changes.removed)
        # todo: move this to some kind of "usage explanation" function, implement rest of this

    @property
    def as_operations(self) -> DatabaseOperationCollection:
        current_objects = {}
        for model_name, changed_objects in self.objects.items():
            model = apps.get_model("mapdata", model_name)
            current_objects[model_name] = {obj.pk: obj for obj in model.objects.filter(pk__in=changed_objects.keys())}

        operations_with_dependencies: list[OperationWithDependencies] = []
        for model_name, changed_objects in self.objects.items():
            model = apps.get_model("mapdata", model_name)

            for changed_obj in changed_objects.values():
                if changed_obj.deleted:
                    if changed_obj.created:
                        continue
                    operations_with_dependencies.append(
                        SingleOperationWithDependencies(
                            operation=DeleteObjectOperation(obj=changed_obj.obj),
                            dependencies={OperationDependencyNoProtectedReference(obj=changed_obj.obj)}
                        ),
                    )
                    continue

                initial_fields = dict()
                obj_operations: list[OperationWithDependencies] = []
                for name, value in changed_obj.fields.items():
                    if value is None:
                        initial_fields[name] = None
                        continue
                    field = model._meta.get_field(name)
                    dependencies = set()
                    # todo: prev
                    if field.is_relation:
                        dependencies.add(OperationDependencyObjectExists(obj=ObjectReference(
                            model=field.related_model._meta.model_name,
                            id=value,
                        )))
                    if field.unique:
                        dependencies.add(OperationDependencyUniqueValue(obj=ObjectReference(
                            model=model._meta.model_name,
                            field=name,
                            value=value,
                        )))

                    if not dependencies:
                        initial_fields[name] = None
                        continue

                    initial_fields[name] = DummyValue
                    obj_operations.append(SingleOperationWithDependencies(
                        operation=UpdateObjectOperation(obj=changed_obj.obj, fields={name: value}),
                        dependencies=dependencies
                    ))

                obj_operations.insert(0, SingleOperationWithDependencies(
                    operation=(CreateObjectOperation if changed_obj.created else UpdateObjectOperation)(
                        obj=changed_obj.obj,
                        fields=initial_fields,
                    )
                ))

                if len(obj_operations) == 1:
                    operations_with_dependencies.append(obj_operations[0])
                else:
                    operations_with_dependencies.append(MergableOperationsWithDependencies(operations=obj_operations))

        from pprint import pprint
        pprint(operations_with_dependencies)

        # todo: continue here

        return DatabaseOperationCollection()
