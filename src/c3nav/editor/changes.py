import bisect
import json
import operator
import random
from functools import reduce
from itertools import chain
from typing import Type, Any, Union, Self, TypeVar, Generic, NamedTuple

from django.apps import apps
from django.core import serializers
from django.core.exceptions import FieldDoesNotExist
from django.db.models import Model, Q, CharField, SlugField, DecimalField
from django.db.models.fields import IntegerField, SmallIntegerField, PositiveIntegerField, PositiveSmallIntegerField
from django.db.models.fields.reverse_related import ManyToOneRel, OneToOneRel
from pydantic.config import ConfigDict

from c3nav.api.schema import BaseSchema
from c3nav.editor.operations import DatabaseOperationCollection, CreateObjectOperation, UpdateObjectOperation, \
    DeleteObjectOperation, ClearManyToManyOperation, FieldValuesDict, ObjectReference, PreviousObjectCollection, \
    DatabaseOperation, ObjectID, FieldName, ModelName, CreateMultipleObjectsOperation, UpdateManyToManyOperation
from c3nav.mapdata.fields import I18nField
from c3nav.mapdata.models import LocationSlug


class ChangedManyToMany(BaseSchema):
    cleared: bool = False
    added: list[ObjectID] = []
    removed: list[ObjectID] = []

    @property
    def __bool__(self):
        return not (self.cleared or self.added or self.removed)


class ChangedObject(BaseSchema):
    obj: ObjectReference
    titles: dict[str, str] | None
    created: bool = False
    deleted: bool = False
    fields: FieldValuesDict = {}
    m2m_changes: dict[FieldName, ChangedManyToMany] = {}

    def __bool__(self):
        return self.created or self.deleted or self.fields or any(self.m2m_changes.values())


class OperationDependencyObjectExists(BaseSchema):
    model_config = ConfigDict(frozen=True)

    obj: ObjectReference


class OperationDependencyUniqueValue(BaseSchema):
    model_config = ConfigDict(frozen=True)

    model: str
    field: FieldName
    value: Any


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
        return self.main_op.dependencies | reduce(operator.or_, (op.dependencies for op in self.sub_ops), set())


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

    # objects that still need to be created before some remaining operation (True = missing)
    missing_objects: dict[ModelName, dict[ObjectID, bool]] = {}

    # unique values relevant for these operations that are currently not free
    occupied_unique_values: dict[ModelName, dict[FieldName, dict[Any, ObjectID | None]]] = {}

    # references to objects that need to be removed for in this run
    obj_references: dict[ModelName, dict[ObjectID, set[FoundObjectReference]]] = {}

    @property
    def dependency_snapshot(self):
        return (
            frozenset(chain(*(
                ((model_name, pk) for pk, missing in objects.items() if missing)
                for model_name, objects in self.missing_objects.items()
            ))),
            frozenset(
                chain(*(
                    chain(*(
                        ((model_name, field_name, field_value) for field_value, pk in values.items() if pk is not None)
                        for field_name, values in fields.items()
                    )) for model_name, fields in self.occupied_unique_values.items()
                ))
            ),
            frozenset(
                chain(*(
                    chain(*(
                        ((model_name, pk, found_ref) for found_ref in found_refs)
                        for pk, found_refs in objects.items()
                    )) for model_name, objects in self.obj_references.items()
                ))
            )
        )

    def fulfils_dependency(self, dependency: OperationDependency) -> bool:
        if isinstance(dependency, OperationDependencyObjectExists):
            return not self.missing_objects.get(dependency.obj.model, {}).get(dependency.obj.id, False)

        if isinstance(dependency, OperationDependencyNoProtectedReference):
            return not any(
                (reference.on_delete == "PROTECT") for reference in
                self.obj_references.get(dependency.obj.model, {}).get(dependency.obj.id, ())
            )

        if isinstance(dependency, OperationDependencyUniqueValue):
            return self.occupied_unique_values.get(dependency.model, {}).get(
                dependency.field, {}
            ).get(dependency.value, None) is None

        raise ValueError

    def fulfils_dependencies(self, dependencies: set[OperationDependency]) -> bool:
        return all(self.fulfils_dependency(dependency) for dependency in dependencies)


class ChangedObjectProblems(BaseSchema):
    obj_does_not_exist: bool = False
    cant_create: bool = False
    protected_references: set[FoundObjectReference] = set()
    field_does_not_exist: set[FieldName] = set()
    m2m_val_does_not_exist: dict[FieldName, set[ObjectID]] = {}
    dummy_values: dict[FieldName, Any] = {}
    ref_doesnt_exist: set[FieldName] = set()
    unique_constraint: set[FieldName] = set()

    def clean(self) -> bool:
        """
        Clean up data and return true if there's any problemls left
        """
        self.m2m_val_does_not_exist = {
            field_name: ids
            for field_name, ids in self.m2m_val_does_not_exist.items()
            if ids
        }
        return (
            self.obj_does_not_exist
            or self.cant_create
            or self.protected_references
            or self.field_does_not_exist
            or self.m2m_val_does_not_exist
            or self.dummy_values
            or self.ref_doesnt_exist
            or self.unique_constraint
        )


class ChangeProblems(BaseSchema):
    model_does_not_exist: set[ModelName] = set()
    objects: dict[ModelName, dict[ObjectID, ChangedObjectProblems]] = {}

    def clean(self):
        self.objects = {
            model_name: problem_objects for
            model_name, problem_objects in (
                (model_name, {pk: obj for pk, obj in problem_objects.items() if obj.clean()})
                for model_name, problem_objects in self.objects.items()
            )
            if problem_objects
        }

    def get_object(self, obj: ObjectReference):
        return self.objects.setdefault(obj.model, {}).setdefault(obj.id, ChangedObjectProblems())

    @property
    def any(self) -> bool:
        """ Are there any problems? """
        return bool(self.model_does_not_exist or self.objects)


# todo: what if model does not exist…


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
                # todo: titles should be better, probably
                titles = (
                    operation.fields.get("title", {})
                    if isinstance(operation, CreateObjectOperation)
                    else self.prev.get(operation.obj).titles
                )
                changed_object = ChangedObject(obj=operation.obj, titles=titles)
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
                changed_object.deleted = True
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
        # todo: what the heck was this function for?
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

    class OperationsWithDependencies(NamedTuple):
        obj_operations: list[OperationWithDependencies]
        m2m_operations: list[SingleOperationWithDependencies]

    @property
    def as_operations_with_dependencies(self) -> tuple[OperationsWithDependencies, ChangeProblems]:
        operations_with_dependencies = self.OperationsWithDependencies(obj_operations=[], m2m_operations=[])
        problems = ChangeProblems()
        for model_name, changed_objects in self.objects.items():
            try:
                model = apps.get_model("mapdata", model_name)
            except LookupError:
                problems.model_does_not_exist.add(model_name)
                continue

            for changed_obj in changed_objects.values():
                base_dependencies: set[OperationDependency] = (
                    set() if changed_obj.created else {OperationDependencyObjectExists(obj=changed_obj.obj)}
                )

                if changed_obj.deleted:
                    if changed_obj.created:
                        continue
                    operations_with_dependencies.obj_operations.append(
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
                for field_name, value in changed_obj.fields.items():
                    try:
                        field = model._meta.get_field(field_name)
                    except FieldDoesNotExist:
                        problems.get_object(changed_obj.obj).field_does_not_exist.add(field_name)
                        continue

                    if value is None:
                        initial_fields[field_name] = None
                        continue
                    dependencies = base_dependencies.copy()
                    # todo: prev
                    if field.is_relation and not field.many_to_many:
                        dependencies.add(OperationDependencyObjectExists(obj=ObjectReference(
                            model=field.related_model._meta.model_name,
                            id=value,
                        )))
                    if field.unique:
                        dependencies.add(OperationDependencyUniqueValue(
                            model="locationslug" if issubclass(model, LocationSlug) else model._meta.model_name,
                            field=field_name,
                            value=value,
                        ))

                    if not dependencies:
                        initial_fields[field_name] = value
                        continue

                    initial_fields[field_name] = None if field.null else DummyValue
                    obj_sub_operations.append(SingleOperationWithDependencies(
                        uid=(changed_obj.obj, f"field_{field_name}"),
                        operation=UpdateObjectOperation(obj=changed_obj.obj, fields={field_name: value}),
                        dependencies=dependencies
                    ))

                obj_main_operation = SingleOperationWithDependencies(
                    uid=(changed_obj.obj, f"main"),
                    operation=(CreateObjectOperation if changed_obj.created else UpdateObjectOperation)(
                        obj=changed_obj.obj,
                        fields=initial_fields,
                    ),
                    dependencies=base_dependencies,
                )

                if not obj_sub_operations:
                    operations_with_dependencies.obj_operations.append(obj_main_operation)
                else:
                    operations_with_dependencies.obj_operations.append(MergableOperationsWithDependencies(
                        main_op=obj_main_operation,
                        sub_ops=obj_sub_operations,
                    ))

                for field_name, m2m_changes in changed_obj.m2m_changes.items():
                    if m2m_changes.cleared:
                        operations_with_dependencies.m2m_operations.append(SingleOperationWithDependencies(
                            uid=(changed_obj.obj, f"m2mclear_{field_name}"),
                            operation=ClearManyToManyOperation(
                                obj=changed_obj.obj,
                                field=field_name,
                            ),
                            dependencies={OperationDependencyObjectExists(obj=changed_obj.obj)},
                        ))
                    if m2m_changes.added or m2m_changes.removed:
                        operations_with_dependencies.m2m_operations.append(SingleOperationWithDependencies(
                            uid=(changed_obj.obj, f"m2mupdate_{field_name}"),
                            operation=UpdateManyToManyOperation(
                                obj=changed_obj.obj,
                                field=field_name,
                                add_values=m2m_changes.added,
                                remove_values=m2m_changes.removed,
                            ),
                            dependencies={OperationDependencyObjectExists(obj=changed_obj.obj)},
                        ))

        return operations_with_dependencies, problems

    class CreateStartOperationResult(NamedTuple):
        situation: OperationSituation
        unique_values_needed: dict[ModelName, dict[FieldName: set]]
        m2m_operations: list[SingleOperationWithDependencies]
        problems: ChangeProblems

    def create_start_operation_situation(self) -> CreateStartOperationResult:
        operations_with_dependencies, problems = self.as_operations_with_dependencies

        start_situation = OperationSituation(
            remaining_operations_with_dependencies=operations_with_dependencies.obj_operations
        )

        referenced_objects: dict[ModelName, set[ObjectID]] = {}  # objects that need to exist before
        deleted_existing_objects: dict[ModelName, set[ObjectID]] = {}  # objects that need to exist before
        unique_values_needed: dict[ModelName, dict[FieldName: set]] = {}
        for operation in operations_with_dependencies.obj_operations:
            for dependency in operation.dependencies:
                if isinstance(dependency, OperationDependencyObjectExists):
                    referenced_objects.setdefault(dependency.obj.model, set()).add(dependency.obj.id)
                elif isinstance(dependency, OperationDependencyUniqueValue):
                    unique_values_needed.setdefault(dependency.model, {}).setdefault(
                        dependency.field, set()
                    ).add(dependency.value)
                elif isinstance(dependency, OperationDependencyNoProtectedReference):
                    deleted_existing_objects.setdefault(dependency.obj.model, set()).add(dependency.obj.id)

        # references from m2m changes need also to be checked if they exist
        for model_name, changed_objects in self.objects.items():
            try:
                model = apps.get_model("mapdata", model_name)
            except LookupError:
                # would already have been reported above
                continue
            # todo: how do we want m2m to work when it's cleared by the user but things were added in the meantime?
            for changed_obj in changed_objects.values():
                for field_name, m2m_changes in changed_obj.m2m_changes.items():
                    try:
                        field = model._meta.get_field(field_name)
                    except FieldDoesNotExist:
                        problems.get_object(changed_obj.obj).field_does_not_exist.add(field_name)
                        continue
                    if field.related_model._meta.app_name != "mapdata":
                        continue
                    referenced_objects.setdefault(
                        field.related_model._meta.model_name, set()
                    ).update(set(m2m_changes.added + m2m_changes.removed))

        # let's find which objects that need to exist before actually exist
        for model, ids in referenced_objects.items():
            model_cls = apps.get_model('mapdata', model)
            ids_found = set(model_cls.objects.filter(pk__in=ids).values_list('pk', flat=True))
            start_situation.missing_objects[model] = {id_: (id_ not in ids_found) for id_ in ids}

        # let's find which unique values are actually occupied right now
        for model, fields in unique_values_needed.items():
            model_cls = apps.get_model('mapdata', model)
            q = Q()
            start_situation.occupied_unique_values[model] = {}
            for field_name, values in fields.items():
                q |= Q(**{f'{field_name}__in': values})
                start_situation.occupied_unique_values[model][field_name] = {value: None for value in values}
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
            ids -= set(start_situation.missing_objects.get(model, {}).keys())
            for field in apps.get_model('mapdata', model)._meta.get_fields():
                if (not isinstance(field, (ManyToOneRel, OneToOneRel))
                        or field.related_model._meta.app_label != "mapdata"):
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
                targets_reverse[field_name] = dict(chain(*(((id_, target_model) for id_ in target_ids)
                                                           for target_model, target_ids in targets.items())))
            for result in model_cls.objects.filter(q).values("id", *fields.keys()):
                source_ref = ObjectReference(model=model, id=result.pop("id"))
                for field, target_id in result.items():
                    target_model = targets_reverse[field][target_id]
                    start_situation.obj_references.setdefault(target_model, {}).setdefault(target_id, set()).add(
                        FoundObjectReference(obj=source_ref, field=field,
                                             on_delete=model_cls._meta.get_field(field).remote_field.on_delete.__name__)
                    )

        return self.CreateStartOperationResult(
            situation=start_situation,
            unique_values_needed=unique_values_needed,
            m2m_operations=operations_with_dependencies.m2m_operations,
            problems=problems,
        )

    class ChangesAsOperations(NamedTuple):
        operations: DatabaseOperationCollection
        problems: ChangeProblems

    @property
    def as_operations(self) -> ChangesAsOperations:
        current_objects = {}
        for model_name, changed_objects in self.objects.items():
            model = apps.get_model("mapdata", model_name)
            current_objects[model_name] = {
                obj["pk"]: obj["fields"]
                for obj in json.loads(
                    serializers.serialize("json", model.objects.filter(pk__in=changed_objects.keys()))
                )
            }

        start_situation, unique_values_needed, m2m_operations, problems = self.create_start_operation_situation()

        # situations still to deal with, sorted by number of operations
        open_situations: list[OperationSituation] = [start_situation]

        # situation that solves for all operations
        done_situation: OperationSituation | None = None

        # situations that ended prematurely
        ended_situations: list[OperationSituation] = []

        # best way to get to a certain dependency snapshot, values are number of operations
        best_dependency_snapshots: dict[tuple, int] = {}

        # unique values in db [only want to check for them once]
        dummy_unique_value_avoid: dict[ModelName, dict[FieldName, frozenset]] = {}
        available_model_ids: dict[ModelName, frozenset] = {}

        if not start_situation.remaining_operations_with_dependencies:
            # nothing to do? then we're done
            done_situation = start_situation

        num = 0

        while open_situations and not done_situation:
            num += 1
            if num > 1000:
                raise ValueError("as_operations might be in an endless loop")

            situation = open_situations.pop(0)

            continued = False
            for i, remaining_operation in enumerate(situation.remaining_operations_with_dependencies):
                # check if the main operation can be run
                if not situation.fulfils_dependencies(remaining_operation.main_op.dependencies):
                    continue

                # determine changes to state
                new_operation = remaining_operation.main_op.operation
                new_remaining_operations = []
                uids_to_add: set[tuple] = {remaining_operation.main_op.uid}
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
                operation_model_name = ("locationslug"
                                        if issubclass(model_cls, LocationSlug)
                                        else new_operation.obj.model)
                if isinstance(new_operation, (CreateObjectOperation, UpdateObjectOperation)):
                    couldnt_fill_dummy = False
                    for field_name, value in tuple(new_operation.fields.items()):
                        if value is DummyValue:
                            # if there's a dummy value to fill, we need to find a dummy value
                            field = model_cls._meta.get_field(field_name)

                            if field.is_relation:
                                # for a relation, we will try to find a valid other object to reference
                                if available_model_ids.get(field.related_model._meta.model_name) is None:
                                    # find available model ids, we only query these once for less queries
                                    available_model_ids[field.related_model._meta.model_name] = frozenset(
                                        field.related_model.objects.values_list('pk', flat=True)
                                    )
                                if field.unique:
                                    # if the field is unique we need to find a value that isn't occupied
                                    # and, to be sure, that we haven't used as a dummyvalue before
                                    if dummy_unique_value_avoid.get(operation_model_name, {}).get(field_name) is None:
                                        dummy_unique_value_avoid.setdefault(
                                            operation_model_name, {}
                                        )[field_name] = frozenset(
                                            model_cls.objects.values_list(field_name.attname, flat=True)
                                        ) | unique_values_needed.get(operation_model_name, {}).get(field_name, set())

                                    choices = (
                                        available_model_ids[field.related_model._meta.model_name] -
                                        dummy_unique_value_avoid[operation_model_name][field_name] -
                                        set(val for val, id_ in situation.occupied_unique_values[
                                                operation_model_name
                                            ][field_name].items() if id_ is not None)
                                    )
                                else:
                                    choices = available_model_ids[field.related_model._meta.model_name]
                                if not choices:
                                    couldnt_fill_dummy = True
                                    break
                                dummy_value = next(iter(choices))
                            else:
                                if field.unique:
                                    # otherwise, an non-relational field needs a unique value
                                    if dummy_unique_value_avoid.get(operation_model_name, {}).get(field_name) is None:
                                        dummy_unique_value_avoid.setdefault(
                                            operation_model_name, {}
                                        )[field_name] = frozenset(
                                            model_cls.objects.values_list(field_name, flat=True)
                                        ) | unique_values_needed.get(operation_model_name, {}).get(field_name, set())
                                    occupied = (
                                        dummy_unique_value_avoid[operation_model_name][field_name] -
                                        set(val for val, id_ in situation.occupied_unique_values[
                                            operation_model_name
                                        ][field_name].items() if id_ is not None)
                                    )
                                else:
                                    # this shouldn't happen, because dummy values are only used by non-relation fields
                                    # for unique constraints
                                    raise NotImplementedError

                                # generate a value that works
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
                                dummy_value = new_val

                            # store the dummyvalue so we can tell the user about it
                            problems.get_object(new_operation.obj).dummy_values[field_name] = dummy_value

                            new_operation.fields[field_name] = dummy_value

                        else:
                            # we have set this field to a non-dummy value, if we used one before we can forget it
                            problems.get_object(new_operation.obj).dummy_values.pop(field_name, None)

                    if couldnt_fill_dummy:
                        continue  # if we couldn't fill a dummy value this operation is not doable, skip it

                # construct new situation
                new_situation = situation.model_copy(deep=True)

                model = apps.get_model('mapdata', new_operation.obj.model)
                for parent in model._meta.get_parent_list():
                    if parent._meta.concrete_model is not model._meta.concrete_model:
                        is_multi_inheritance = True
                        break
                else:
                    is_multi_inheritance = False

                if (isinstance(new_operation, CreateObjectOperation)
                        and new_situation.operations and not is_multi_inheritance):
                    last_operation = new_situation.operations[-1]
                    if (isinstance(last_operation, CreateObjectOperation)
                            and last_operation.obj.model == new_operation.obj.model):
                        new_situation.operations[-1] = CreateMultipleObjectsOperation(
                            objects=[last_operation, new_operation],
                        )
                    elif (isinstance(last_operation, CreateMultipleObjectsOperation) and
                            len(last_operation.objects) < 25 and
                            last_operation.objects[-1].obj.model == new_operation.obj.model):
                        last_operation.objects.append(new_operation)
                    else:
                        new_situation.operations.append(new_operation)
                else:
                    if not (isinstance(new_operation, UpdateObjectOperation) and not new_operation.fields):
                        # we might have empty update operations, those can be ignored
                        new_situation.operations.append(new_operation)

                new_situation.remaining_operations_with_dependencies.pop(i)
                new_situation.remaining_operations_with_dependencies.extend(new_remaining_operations)
                new_situation.operation_uids = new_situation.operation_uids | uids_to_add

                # even if we don't actually continue cause better paths existed, this situation is not a deadlock
                continued = True

                if not new_situation.remaining_operations_with_dependencies:
                    # nothing left to do, congratulations we did it!
                    done_situation = new_situation
                    break

                dependency_snapshot = (new_situation.dependency_snapshot, len(new_situation.operation_uids))
                if best_dependency_snapshots.get(dependency_snapshot, 1000000) <= len(new_situation.operations):
                    # we already reached this dependency snapshot with the same number of operations
                    # in a better way
                    continue

                if isinstance(new_operation, CreateObjectOperation):
                    # if an object was created it's no longer missing
                    for mn in {new_operation.obj.model, operation_model_name}:
                        missing_objects = new_situation.missing_objects.get(mn, {})
                        if new_operation.obj.id in missing_objects:
                            missing_objects[new_operation.obj.id] = False

                if isinstance(new_operation, UpdateObjectOperation):
                    occupied_unique_values = new_situation.occupied_unique_values.get(new_operation.obj.model, {})
                    relations_changed = set()
                    for field_name in new_operation.fields:
                        field = model_cls._meta.get_field(field_name)
                        if field.unique:
                            # unique field was changed? remove unique value entry [might be readded below]
                            occupied_unique_values[field_name] = {
                                val: (None if new_operation.obj.id == pk else pk)
                                for val, pk in occupied_unique_values.get(field_name, {}).items()
                            }
                        if field.is_relation:
                            relations_changed.add(field_name)

                    if relations_changed:
                        # relation field was changed? remove reference entry [might be readded below]
                        for model_name, references in tuple(new_situation.obj_references.items()):
                            new_situation.obj_references[model_name] = {
                                pk: ref for pk, ref in references.items()
                                if ref.obj != new_operation.obj or ref.field not in relations_changed
                            }

                if isinstance(new_operation, DeleteObjectOperation):
                    # if an object was deleted it will now be missing
                    for mn in {new_operation.obj.model, operation_model_name}:
                        missing_objects = new_situation.missing_objects.get(mn, {})
                        if new_operation.obj.id in missing_objects:
                            missing_objects[new_operation.obj.id] = True

                    # all unique values it occupied will no longer be occupied
                    occupied_unique_values = new_situation.occupied_unique_values.get(new_operation.obj.model, {})
                    for field_name, values in tuple(occupied_unique_values.items()):
                        occupied_unique_values[field_name] = {val: (None if new_operation.obj.id == pk else pk)
                                                              for val, pk in values.items()}

                    # all references that came from it, will no longer exist
                    for model_name, references in tuple(new_situation.obj_references.items()):
                        new_situation.obj_references[model_name] = {
                            pk: {ref for ref in refs if ref.obj != new_operation.obj}
                            for pk, refs in references.items()
                        }

                    # todo: we ignore cascading for now, do we want to keep it that way? probably not!
                else:
                    for field_name, value in new_operation.fields.items():
                        field = model_cls._meta.get_field(field_name)
                        if value is None:
                            continue
                        if field.unique:
                            # unique field was changed? add unique value entry
                            field_occupied_values = new_situation.occupied_unique_values.get(
                                new_operation.obj.model, {}
                            ).get(field_name, {})
                            if value in field_occupied_values:
                                field_occupied_values[value] = new_operation.obj.id
                        if field.is_relation and not field.many_to_many:
                            # relation field was changed? add foundobjectreference
                            model_refs = new_situation.obj_references.get(field.related_model._meta.model_name, {})
                            if value in model_refs:
                                model_refs[value].add(
                                    FoundObjectReference(
                                        obj=new_operation.obj,
                                        field=field_name,
                                        on_delete=field.remote_field.on_delete.__name__,
                                    )
                                )

                # finally insert new situation
                bisect.insort(open_situations, new_situation,
                              key=lambda s: (len(s.operations), ))

                best_dependency_snapshots[dependency_snapshot] = len(new_situation.operations)

            if not continued:
                ended_situations.append(situation)

        if not done_situation:
            done_situation = max(ended_situations, key=lambda s: (len(s.operation_uids), -len(s.operations)))

        # add m2m
        for m2m_operation_with_dependencies in m2m_operations:
            if not done_situation.fulfils_dependencies(m2m_operation_with_dependencies.dependencies):
                done_situation.remaining_operations_with_dependencies.append(m2m_operation_with_dependencies)
                continue
            done_situation.operations.append(m2m_operation_with_dependencies.operation)

        for remaining_operation in done_situation.remaining_operations_with_dependencies:
            model_cls = apps.get_model("mapdata", remaining_operation.main_op.operation.obj.model)
            obj = remaining_operation.main_op.operation.obj
            problem_obj = problems.get_object(obj)
            if done_situation.missing_objects.get(obj.model, {}).get(obj.id):
                problem_obj.obj_does_not_exist = True
                continue

            if isinstance(remaining_operation.main_op, DeleteObjectOperation):
                problem_obj.protected_references = {
                    found_ref for found_ref in done_situation.obj_references.get(
                        remaining_operation.main_op.obj.model, {}
                    )[remaining_operation.main_op.obj.id]
                    if found_ref.on_delete == "PROTECT"
                }
                # this will fail if there are no protected references because that should never happen
                continue

            if isinstance(remaining_operation.main_op, CreateObjectOperation):
                problem_obj.cant_create = True

            sub_ops = (chain((remaining_operation.main_op,), remaining_operation.sub_ops)
                       if isinstance(remaining_operation, MergableOperationsWithDependencies)
                       else (remaining_operation.main_op,))
            for sub_op in sub_ops:
                if isinstance(sub_op, UpdateManyToManyOperation):
                    related_model_name = model_cls._meta.get_field(sub_op.field).related_model._meta.model_name
                    missing_ids = (
                        set(id_ for id_, missing in done_situation.missing_objects.get(related_model_name, {}).items()
                            if missing) &
                        (sub_op.add_values | sub_op.remove_values)
                    )
                    if missing_ids:
                        problem_obj[sub_op.field] = missing_ids
                elif isinstance(sub_op, UpdateObjectOperation):
                    for dependency in sub_op.dependencies:
                        if isinstance(dependency, OperationDependencyObjectExists) and dependency.obj != sub_op.obj:
                            problem_obj.ref_doesnt_exist.update(set(sub_op.fields.keys()))
                        elif isinstance(dependency, OperationDependencyUniqueValue):
                            problem_obj.unique_constraint.update(set(sub_op.fields.keys()))

        problems.clean()

        return self.ChangesAsOperations(
            operations=DatabaseOperationCollection(
                prev=self.prev,
                operations=done_situation.operations,
            ),
            problems=problems
        )
