import bisect
import json
import operator
import random
from functools import reduce
from itertools import chain
from typing import Type, Any, Union, Self, TypeVar, Generic

from django.apps import apps
from django.core import serializers
from django.db.models import Model, Q, CharField, SlugField, DecimalField
from django.db.models.fields import IntegerField, SmallIntegerField, PositiveIntegerField, PositiveSmallIntegerField
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
    model_config = ConfigDict(frozen=True)

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


# todo: switch to new syntax once pydantic supports it
OperationT = TypeVar('OperationT', bound=DatabaseOperation)


class SingleOperationWithDependencies(BaseSchema, Generic[OperationT]):
    uid: tuple
    operation: OperationT
    dependencies: set[OperationDependency] = set()

    @property
    def main_op(self) -> Self:
        return self


class MergableOperationsWithDependencies(BaseSchema):
    main_op: Union[
        SingleOperationWithDependencies[CreateObjectOperation],
        SingleOperationWithDependencies[UpdateObjectOperation],
    ]
    sub_ops: list[SingleOperationWithDependencies[UpdateObjectOperation]]

    @property
    def dependencies(self) -> set[OperationDependency]:
        return reduce(operator.or_, (c.dependencies for c in self.children), set())


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


class OperationSituation(BaseSchema):
    # operations done so far
    operations: list[DatabaseOperation] = []

    # uids of operationswithdependencies that are included now
    operation_uids: frozenset[tuple] = frozenset()

    # remaining operations still to do
    remaining_operations_with_dependencies: list[OperationWithDependencies] = []

    # objects that still need to be created before some remaining operation (or that were simply deleted in this run)
    missing_objects: dict[ModelName, set[ObjectID]] = {}

    # unique values relevant for these operations that are currently not free
    occupied_unique_values: dict[ModelName, dict[FieldName, dict[Any, ObjectID]]] = {}

    # references to objects that need to be removed for in this run
    obj_references: dict[ModelName, dict[ObjectID, set[FoundObjectReference]]] = {}

    def fulfils_dependency(self, dependency: OperationDependency) -> bool:
        if isinstance(dependency, OperationDependencyObjectExists):
            return dependency.obj.id not in self.missing_objects.get(dependency.obj.model, set())

        if isinstance(dependency, OperationDependencyNoProtectedReference):
            return not any(
                (reference.on_delete == "PROTECT") for reference in
                self.obj_references.get(dependency.obj.model, {}).get(dependency.obj.id, ())
            )

        if isinstance(dependency, OperationDependencyUniqueValue):
            return dependency.value not in self.occupied_unique_values.get(dependency.obj.model,
                                                                           {}).get(dependency.field, set())

        raise ValueError

    def fulfils_dependencies(self, dependencies: set[OperationDependency]) -> bool:
        return all(self.fulfils_dependency(dependency) for dependency in dependencies)


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
    def as_operations_with_dependencies(self) -> list[OperationWithDependencies]:
        operations_with_dependencies: list[OperationWithDependencies] = []
        for model_name, changed_objects in self.objects.items():
            model = apps.get_model("mapdata", model_name)

            for changed_obj in changed_objects.values():
                base_dependencies: set[OperationDependency] = (
                    set() if changed_obj.created else {OperationDependencyObjectExists(obj=changed_obj.obj)}
                )

                if changed_obj.deleted:
                    if changed_obj.created:
                        continue
                    operations_with_dependencies.append(
                        SingleOperationWithDependencies(
                            uid=(changed_obj.obj, "delete"),
                            operation=DeleteObjectOperation(obj=changed_obj.obj),
                            dependencies=(
                                base_dependencies | {OperationDependencyNoProtectedReference(obj=changed_obj.obj)}
                            ),
                        ),
                    )
                    continue

                initial_fields = dict()
                obj_sub_operations: list[OperationWithDependencies] = []
                for name, value in changed_obj.fields.items():
                    if value is None:
                        initial_fields[name] = None
                        continue
                    field = model._meta.get_field(name)
                    dependencies = base_dependencies.copy()
                    # todo: prev
                    if field.is_relation:
                        dependencies.add(OperationDependencyObjectExists(obj=ObjectReference(
                            model=field.related_model._meta.model_name,
                            id=value,
                        )))
                    if field.unique:
                        dependencies.add(OperationDependencyUniqueValue(
                            model=model._meta.model_name,
                            field=name,
                            value=value,
                        ))

                    if not dependencies:
                        initial_fields[name] = None
                        continue

                    initial_fields[name] = DummyValue
                    obj_sub_operations.append(SingleOperationWithDependencies(
                        uid=(changed_obj.obj, f"field_{name}"),
                        operation=UpdateObjectOperation(obj=changed_obj.obj, fields={name: value}),
                        dependencies=dependencies
                    ))

                obj_main_operation = SingleOperationWithDependencies(
                    operation=(CreateObjectOperation if changed_obj.created else UpdateObjectOperation)(
                        uid=(changed_obj.obj, f"main"),
                        obj=changed_obj.obj,
                        fields=initial_fields,
                    ),
                    dependencies=base_dependencies,
                )

                if not obj_sub_operations:
                    operations_with_dependencies.append(obj_main_operation)
                else:
                    operations_with_dependencies.append(MergableOperationsWithDependencies(
                        main_op=obj_main_operation,
                        sub_ops=obj_sub_operations,
                    ))
        return operations_with_dependencies

    def create_start_operation_situation(self) -> tuple[OperationSituation, dict[ModelName, dict[FieldName: set]]]:
        operations_with_dependencies = self.as_operations_with_dependencies

        from pprint import pprint
        pprint(operations_with_dependencies)

        start_situation = OperationSituation(remaining_operations_with_dependencies=operations_with_dependencies)

        referenced_objects: dict[ModelName, set[ObjectID]] = {}  # objects that need to exist before
        deleted_existing_objects: dict[ModelName, set[ObjectID]] = {}  # objects that need to exist before
        unique_values_needed: dict[ModelName, dict[FieldName: set]] = {}
        for operation in operations_with_dependencies:
            for dependency in operation.dependencies:
                if isinstance(dependency, OperationDependencyObjectExists):
                    referenced_objects.setdefault(dependency.obj.model, set()).add(dependency.obj.id)
                elif isinstance(dependency, OperationDependencyUniqueValue):
                    unique_values_needed.setdefault(
                        dependency.obj.model, {}
                    ).setdefault(dependency.field, set()).add(dependency.value)
                elif isinstance(dependency, OperationDependencyNoProtectedReference):
                    deleted_existing_objects.setdefault(dependency.obj.model, set()).add(dependency.obj.id)

        # let's find which objects that need to exist before actually exist
        for model, ids in referenced_objects.items():
            model_cls = apps.get_model('mapdata', model)
            ids_found = set(model_cls.objects.filter(pk__in=ids).values_list('pk', flat=True))
            start_situation.missing_objects[model] = {id_ for id_ in ids if id_ not in ids_found}

        # let's find which unique values are actually occupied right now
        for model, fields in unique_values_needed.items():
            model_cls = apps.get_model('mapdata', model)
            q = Q()
            for field_name, values in fields.items():
                q |= Q(**{f'{field_name}__in': values})
            start_situation.occupied_unique_values[model] = {}
            for result in model_cls.objects.filter(q).values("id", *fields.keys()):
                pk = result.pop("id")
                for field_name, value in result.items():
                    if value in fields[field_name]:
                        start_situation.occupied_unique_values[model].setdefault(field_name, {})[value] = pk

        # let's find which protected references to objects we want to delete have
        potential_fields: dict[ModelName, dict[FieldName, dict[ModelName, set[ObjectID]]]] = {}
        for model, ids in deleted_existing_objects.items():
            # don't check this for objects that don't exist anymore
            ids -= start_situation.missing_objects.get(model, set())
            for field in apps.get_model('mapdata', model)._meta.get_fields():
                if isinstance(field, (ManyToOneRel, OneToOneRel)) or field.model._meta.app_label != "mapdata":
                    continue
                potential_fields.setdefault(field.related_model._meta.model_name,
                                            {}).setdefault(field.field.attname, {})[model] = ids

        # collect all references to objects we want to delete
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
                    start_situation.obj_references.setdefault(target_model, {}).setdefault(target_id, set()).add(
                        FoundObjectReference(obj=source_ref, field=field,
                                             on_delete=model_cls._meta.get_field(field).on_delete.__name__)
                    )

        return start_situation, unique_values_needed

    @property
    def as_operations(self) -> DatabaseOperationCollection:
        current_objects = {}
        for model_name, changed_objects in self.objects.items():
            model = apps.get_model("mapdata", model_name)
            current_objects[model_name] = {
                obj["pk"]: obj["fields"]
                for obj in json.loads(
                    serializers.serialize("json", model.objects.filter(pk__in=changed_objects.keys()))
                )
            }

        start_situation, unique_values_needed = self.create_start_operation_situation()

        # situations still to deal with, sorted by number of operations
        open_situations: list[OperationSituation] = [start_situation]

        # situation that solves for all operations
        done_situation: OperationSituation | None = None

        # situations that ended prematurely, todo: sort by something?
        ended_situations: list[OperationSituation] = []

        # situations already encountered by set of operation uuids included, values are number of operations
        best_uids:  dict[frozenset[tuple], int] = {}

        # unique values in db [only want to check for them once]
        dummy_unique_value_avoid: dict[ModelName, dict[FieldName, frozenset]] = {}
        available_model_ids: dict[ModelName, frozenset] = {}

        while open_situations and not done_situation:
            situation = open_situations.pop(0)

            continued = False
            for i, remaining_operation in enumerate(situation.remaining_operation_with_dependencies):
                # check if the main operation can be ran
                if not situation.fulfils_dependencies(remaining_operation.main_op.dependencies):
                    continue

                # determine changes to state
                new_operation = remaining_operation.main_op.operation
                new_remaining_operations = []
                uids_to_add: set[tuple] = set(remaining_operation.main_op.uid)
                if isinstance(remaining_operation, MergableOperationsWithDependencies):
                    # sub_ops to be merged into this one or become pending operations
                    new_operation: Union[CreateObjectOperation, UpdateObjectOperation]
                    for sub_op in remaining_operation.sub_ops:
                        if situation.fulfils_dependencies(sub_op.dependencies):
                            new_operation.fields.update(sub_op.operation.fields)
                            uids_to_add.add(sub_op.uid)
                        else:
                            new_remaining_operations.append(sub_op)

                model_cls = apps.get_model('mapdata', new_operation.obj.model)
                if isinstance(new_operation, (CreateObjectOperation, UpdateObjectOperation)):
                    for field_name, value in tuple(new_operation.fields.items()):
                        if value is DummyValue:
                            field = model_cls._meta.get_field(field_name)
                            if field.null:
                                new_operation.fields[field_name] = None
                                continue

                            # todo: tell user about DummyValue result somehow
                            if field.is_relation:

                                if available_model_ids.get(field.related_model._meta.model_name) is None:
                                    available_model_ids[field.related_model._meta.model_name] = frozenset(
                                        field.related_model.objects.values_list('pk', flat=True)
                                    )
                                if field.unique:
                                    if dummy_unique_value_avoid.get(new_operation.obj.model, {}).get(field_name) is None:
                                        dummy_unique_value_avoid.setdefault(
                                            new_operation.obj.model, {}
                                        )[field_name] = frozenset(
                                            model_cls.objects.values_list(field_name, flat=True)
                                        ) | unique_values_needed.get(new_operation.obj.model, {}).get(field_name, set())

                                    choices = (
                                        available_model_ids[field.related_model._meta.model_name] -
                                        dummy_unique_value_avoid[new_operation.obj.model][field_name] -
                                        set(
                                            situation.occupied_unique_values[new_operation.obj.model][field_name].keys()
                                        )
                                    )
                                else:
                                    choices = available_model_ids[field.related_model._meta.model_name]
                                if not choices:
                                    raise NotImplementedError  # todo: inform user about impossibility
                                new_operation.fields[field_name] = next(iter(choices))
                                continue

                            if field.is_relation:
                                if field.unique:
                                    if dummy_unique_value_avoid.get(new_operation.obj.model, {}).get(field_name) is None:
                                        dummy_unique_value_avoid.setdefault(
                                            new_operation.obj.model, {}
                                        )[field_name] = frozenset(
                                            model_cls.objects.values_list(field_name, flat=True)
                                        ) | unique_values_needed.get(new_operation.obj.model, {}).get(field_name, set())
                                    occupied = (
                                        dummy_unique_value_avoid[new_operation.obj.model][field_name] -
                                        set(
                                            situation.occupied_unique_values[new_operation.obj.model][field_name].keys()
                                        )
                                    )
                                else:
                                    occupied = frozenset()
                                if isinstance(field, (SlugField, CharField)):
                                    new_val = "dummyvalue"
                                    while new_val in occupied:
                                        new_val = "dummyvalue"+str(random.randrange(1, 10000000))
                                elif isinstance(field, (DecimalField, IntegerField, SmallIntegerField,
                                                        PositiveIntegerField, PositiveSmallIntegerField)):
                                    new_val = 0
                                    while new_val in occupied:
                                        new_val += 1
                                else:
                                    raise NotImplementedError
                                new_operation.fields[field_name] = new_val

                # construct new situation
                new_situation = situation.model_copy(deep=True)
                new_situation.remaining_operations_with_dependencies.pop(i)
                new_situation.operations.append(new_operation)
                new_situation.remaining_operations_with_dependencies.extend(new_remaining_operations)
                new_situation.operation_uids = new_situation.operation_uids | uids_to_add

                # even if we don't actually continue cause better paths existed, this situation is not a deadlock
                continued = True

                if not new_situation.remaining_operations_with_dependencies:
                    # nothing left to do, congratulations we did it!
                    done_situation = new_situation
                    break

                if best_uids.get(new_situation.operation_uids, 1000000) <= len(new_situation.operations):
                    # we already reached this situation with the same or less amount of operations
                    continue

                # todo: finish this...

                # todo: don't forget nullable references and unique values

                if isinstance(new_operation, CreateObjectOperation):
                    # if an object was created it's no longer missing
                    new_situation.missing_objects.get(new_operation.obj.model, set()).discard(new_operation.obj.id)

                if isinstance(new_operation, UpdateObjectOperation):
                    occupied_unique_values = new_situation.occupied_unique_values.get(new_operation.obj.model, {})
                    relations_changed = set()
                    for field_name in new_operation.fields:
                        field = model_cls._meta.get_field(field_name)
                        if field.unique:
                            # unique field was changed? remove unique value entry [might be readded below]
                            occupied_unique_values[field_name] = {
                                val: pk for val, pk in occupied_unique_values[field_name].items()
                                if pk != new_operation.obj.model
                            }
                        if field.is_relation:
                            relations_changed.add(field_name)
                            # unique field was changed? remove unique value entry [might be readded below]
                            occupied_unique_values[field_name] = {
                                val: pk for val, pk in occupied_unique_values[field_name].items()
                                if pk != new_operation.obj.model
                            }

                    if relations_changed:
                        # relation field was changed? remove reference entry [might be readded below]
                        for model_name, references in tuple(new_situation.obj_references.items()):
                            new_situation.obj_references[model_name] = {
                                pk: ref for pk, ref in references.items()
                                if ref.obj != new_operation.obj or ref.field not in relations_changed
                            }

                if isinstance(new_operation, DeleteObjectOperation):
                    # if an object was deleted it will now be missing
                    new_situation.missing_objects.get(new_operation.obj.model, set()).add(new_operation.obj.id)

                    # all unique values it occupied will no longer be occupied
                    occupied_unique_values = new_situation.occupied_unique_values.get(new_operation.obj.model, {})
                    for field_name, values in tuple(occupied_unique_values.items()):
                        occupied_unique_values[field_name] = {val: pk for val, pk in values.items()
                                                              if pk != new_operation.obj.model}

                    # all references that came from it, will no longer exist
                    for model_name, references in tuple(new_situation.obj_references.items()):
                        new_situation.obj_references[model_name] = {
                            pk: ref for pk, ref in references.items()
                            if ref.obj != new_operation.obj
                        }

                    # todo: cascading…?
                else:
                    pass  # todo: add new unique values and references

                # todo: ...to this

                # finally insert new situation
                bisect.insort(open_situations, new_situation, key=lambda s: len(s.operations))
                best_uids[new_situation.operation_uids] = len(new_situation.operations)

            if not continued:
                ended_situations.append(situation)

        if done_situation:
            return DatabaseOperationCollection(
                prev=self.prev,
                _operations=done_situation.operations,
            )

        # todo: what to do if we can't fully solve it?
        raise NotImplementedError('couldnt fully solve as_operations')
