import operator
from functools import reduce
from itertools import chain
from typing import Type, Any, Union

from django.apps import apps
from django.db.models import Model, Q
from django.db.models.fields.reverse_related import ManyToOneRel, OneToOneRel
from pydantic.config import ConfigDict

from c3nav.api.schema import BaseSchema
from c3nav.editor.operations import DatabaseOperationCollection, CreateObjectOperation, UpdateObjectOperation, \
    DeleteObjectOperation, ClearManyToManyOperation, FieldValuesDict, ObjectReference, PreviousObjectCollection, \
    DatabaseOperation, ObjectID, FieldName, ModelName
from c3nav.mapdata.fields import I18nField


class ChangedManyToMany(BaseSchema):
    cleared: bool = False
    added: list[ObjectID] = []
    removed: list[ObjectID] = []


class ChangedObject(BaseSchema):
    obj: ObjectReference
    titles: dict[str, str] | None
    created: bool = False
    deleted: bool = False
    fields: FieldValuesDict = {}
    m2m_changes: dict[FieldName, ChangedManyToMany] = {}


class OperationDependencyObjectExists(BaseSchema):
    obj: ObjectReference
    nullable: bool


class OperationDependencyUniqueValue(BaseSchema):
    model_config = ConfigDict(frozen=True)

    model: str
    field: FieldName
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

    @property
    def main_operation(self) -> DatabaseOperation:
        return self.operation


class MergableOperationsWithDependencies(BaseSchema):
    children: list[SingleOperationWithDependencies]

    @property
    def dependencies(self) -> set[OperationDependency]:
        return reduce(operator.or_, (c.dependencies for c in self.children), set())

    @property
    def main_operation(self) -> DatabaseOperation:
        return self.children[0].operation


OperationWithDependencies = Union[
    SingleOperationWithDependencies,
    MergableOperationsWithDependencies,
]


class FoundObjectReference(BaseSchema):
    model_config = ConfigDict(frozen=True)

    obj: ObjectReference
    field: FieldName
    on_delete: str


class DummyValue:
    pass


class ChangedObjectCollection(BaseSchema):
    """
    A collection of ChangedObject instances, sorted by model and id.
    Also stores a PreviousObjectCollection for comparison with the current state.
    Iterable as a list of ChangedObject instances.
    """
    prev: PreviousObjectCollection = PreviousObjectCollection()
    objects: dict[ModelName, dict[ObjectID, ChangedObject]] = {}

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
        ids: dict[ModelName, set[ObjectID]] = {}
        for model_name, changed_objects in self.objects.items():
            ids.setdefault(model_name, set()).update(set(changed_objects.keys()))
            model = apps.get_model("mapdata", model_name)
            relations: dict[FieldName, Type[Model]] = {field.name: field.related_model
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

        # categorize operations to collect data for simulation/solving and problem detection
        objects_to_delete: dict[ModelName, set[ObjectID]] = {}  # objects that will be deleted [find references!]
        objects_to_exist_before: dict[ModelName, set[ObjectID]] = {}  # objects that need to exist before
        objects_to_create: dict[ModelName, set[ObjectID]] = {}  # objects that will be created
        values_to_clear: dict[ModelName, dict[FieldName: set]]
        for operation in operations_with_dependencies:
            main_operation = operation.main_operation
            if isinstance(main_operation, DeleteObjectOperation):
                objects_to_delete.setdefault(main_operation.obj.model, set()).add(main_operation.obj.id)
                objects_to_exist_before.setdefault(main_operation.obj.model, set()).add(main_operation.obj.id)

            if isinstance(main_operation, UpdateObjectOperation):
                objects_to_exist_before.setdefault(main_operation.obj.model, set()).add(main_operation.obj.id)
            else:
                objects_to_create.setdefault(main_operation.obj.model, set()).add(main_operation.obj.id)

            for dependency in operation.dependencies:
                if isinstance(dependency, OperationDependencyObjectExists):
                    objects_to_exist_before.setdefault(dependency.obj.model, set()).add(dependency.obj.id)
                elif isinstance(dependency, OperationDependencyUniqueValue):
                    values_to_clear.setdefault(dependency.obj.model, {}).setdefault(dependency.field, set()).add(dependency.value)
                    # todo: check for duplicate unique values

        # objects that we create do not need to exist before
        for model, ids in objects_to_create.items():
            objects_to_exist_before.get(model, set()).difference_update(ids)

        # let's find which objects that need to exist before actually exist
        objects_exist_before: dict[ModelName, dict[ObjectID, bool]] = {}
        for model, ids in objects_to_exist_before.items():
            model_cls = apps.get_model('mapdata', model)
            ids_found = set(model_cls.objects.filter(pk__in=ids).values_list('pk', flat=True))
            objects_exist_before[model] = {id_: (id_ in ids_found) for id_ in ids}

        # let's find which protected references objects we want to delete have
        potential_fields: dict[ModelName, dict[FieldName, dict[ModelName, set[ObjectID]]]] = {}
        for model, ids in objects_to_exist_before.items():
            for field in apps.get_model('mapdata', model)._meta.get_fields():
                if isinstance(field, (ManyToOneRel, OneToOneRel)) or field.model._meta.app_label != "mapdata":
                    continue
                potential_fields.setdefault(field.related_model._meta.model_name,
                                            {}).setdefault(field.field.attname, {})[model] = ids

        # collect all references
        found_obj_references: dict[ModelName, dict[ObjectID, set[FoundObjectReference]]] = {}
        for model, fields in potential_fields.items():
            model_cls = apps.get_model('mapdata', model)
            q = Q()
            targets_reverse: dict[FieldName, dict[ObjectID, ModelName]] = {}
            for field_name, targets in fields.items():
                ids = reduce(operator.or_, targets.values(), set())
                q |= Q(**{f'{field_name}__in': ids})
                targets_reverse[field_name] = dict(chain(*(((id_, target_model) for id_, in target_ids)
                                                           for target_model, target_ids in targets)))
            for result in model_cls.objects.filter(q).values("id", *fields.keys()):
                source_ref = ObjectReference(model=model, id=result.pop("id"))
                for field, target_id in result.items():
                    target_model = targets_reverse[field][target_id]
                    found_obj_references.setdefault(target_model, {}).setdefault(target_id, set()).add(
                        FoundObjectReference(obj=source_ref, field=field,
                                             on_delete=model_cls._meta.get_field(field).on_delete.__name__)
                    )

        errors = []

        old_operations_with_dependencies = operations_with_dependencies
        for operation_with_dependencies in old_operations_with_dependencies:
            pass

        # todo: continue here

        return DatabaseOperationCollection()
