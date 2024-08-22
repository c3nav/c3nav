import datetime
import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TypeAlias, Literal, Annotated, Union, Type, Any

from django.core import serializers
from django.db import transaction
from django.db.models import Model
from django.db.models.fields.related import OneToOneField, ForeignKey
from django.utils import timezone
from pydantic import ConfigDict, Discriminator
from pydantic.fields import Field

from c3nav.api.schema import BaseSchema

try:
    from asgiref.local import Local as LocalContext
except ImportError:
    from threading import local as LocalContext


FieldValuesDict: TypeAlias = dict[str, Any]
ExistingOrCreatedID: TypeAlias = int  # negative = temporary ID of created object


class ObjectReference(BaseSchema):
    model_config = ConfigDict(frozen=True)
    model: str
    id: ExistingOrCreatedID

    @classmethod
    def simple_from_instance(cls, instance: Model):
        """
        This method will not convert the ID yet!
        """
        return cls(model=instance._meta.model_name, id=instance.pk)


class BaseChange(BaseSchema):
    obj: ObjectReference
    datetime: Annotated[datetime.datetime, Field(default_factory=timezone.now)]


class CreateObjectChange(BaseChange):
    type: Literal["create"] = "create"
    fields: FieldValuesDict


class UpdateObjectChange(BaseChange):
    type: Literal["update"] = "update"
    fields: FieldValuesDict


class DeleteObjectChange(BaseChange):
    type: Literal["delete"] = "delete"


class AddManyToManyChange(BaseSchema):
    type: Literal["m2m_add"] = "m2m_add"
    field: str
    values: list[int]


class RemoveManyToManyChange(BaseSchema):
    type: Literal["m2m_remove"] = "m2m_remove"
    field: str
    values: list[int]


class ClearManyToManyChange(BaseSchema):
    type: Literal["m2m_clear"] = "m2m_clear"
    field: str


ChangeSetChange = Annotated[
    Union[
        CreateObjectChange,
        UpdateObjectChange,
        DeleteObjectChange,
        AddManyToManyChange,
        RemoveManyToManyChange,
        ClearManyToManyChange,
    ],
    Discriminator("type"),
]


class ChangeSetChanges(BaseSchema):
    prev_reprs: dict[ObjectReference, str] = {}
    prev_values: dict[ObjectReference, FieldValuesDict] = {}
    prev_m2m: dict[ObjectReference, dict[str, list[int]]] = {}
    changes: list[ChangeSetChange] = []


overlay_state = LocalContext()


class InterceptAbortTransaction(Exception):
    pass


@contextmanager
def enable_changeset_overlay(changeset):
    try:
        with transaction.atomic():
            manager = ChangesetOverlayManager(changeset.changes)
            overlay_state.manager = manager
            # todo: apply changes so far
            yield
            raise InterceptAbortTransaction
    except InterceptAbortTransaction:
        pass
    finally:
        overlay_state.manager = None


@dataclass
class ChangesetOverlayManager:
    changes: ChangeSetChanges
    new_changes: bool = False
    pre_change_values: dict[ObjectReference, FieldValuesDict] = field(default_factory=dict)

    # maps negative IDs of created objects to the ID during the current transaction
    mapped_ids: dict[ObjectReference, int] = field(default_factory=dict)

    # maps IDs as used during the current transaction to the negative IDs
    reverse_mapped_ids: dict[ObjectReference, int] = field(default_factory=dict)

    def ref_lookup(self, ref: ObjectReference):
        local_value = self.mapped_ids.get(ref, None)
        return ref if local_value is None else ObjectReference(model=ref.model, id=local_value)

    def reverse_ref_lookup(self, ref: ObjectReference):
        created_value = self.reverse_mapped_ids.get(ref, None)
        return ref if created_value is None else ObjectReference(model=ref.model, id=created_value)

    def get_model_field_values(self, instance: Model) -> FieldValuesDict:
        values = json.loads(serializers.serialize("json", [instance]))[0]["fields"]
        for field in instance._meta.get_fields():
            if field.name not in values:
                continue
            if isinstance(field, (OneToOneField, ForeignKey)):
                value = values[field.name]
                if value is not None:
                    values[field.name] = self.reverse_ref_lookup(
                        ObjectReference(model=field.model._meta.model_name, id=value)
                    ).id
        return values

    def handle_pre_change_instance(self, sender: Type[Model], instance: Model, **kwargs):
        if instance.pk is None:
            return
        ref = ObjectReference.simple_from_instance(instance)
        if ref in self.reverse_mapped_ids:
            return
        if ref not in self.pre_change_values and ref not in self.changes.prev_values:
            self.pre_change_values[ref] = self.get_model_field_values(
                instance._meta.model.objects.get(pk=instance.pk)
            )

    def handle_post_save(self, sender: Type[Model], instance: Model, created: bool,
                         update_fields: set | None, **kwargs):
        field_values = self.get_model_field_values(instance)

        if created:
            created_id = min([change.obj.id for change in self.changes
                              if isinstance(change, CreateObjectChange)], default=0)-1
            model_name = instance._meta.model_name
            self.mapped_ids[ObjectReference(model=model_name, id=created_id)] = instance.pk
            self.reverse_mapped_ids[ObjectReference(model=model_name, id=instance.pk)] = created_id
            self.changes.changes.append(CreateObjectChange(
                obj=ObjectReference(model=instance._meta.model_name, id=created_id),
                fields=field_values
            ))
            from pprint import pprint
            pprint(self.changes)
            return

        if update_fields:
            field_values = {name: value for name, value in field_values.items() if name in update_fields}

        ref = self.reverse_ref_lookup(ObjectReference.simple_from_instance(instance))
        pre_change_values = self.pre_change_values.pop(ref, None)
        if pre_change_values:
            self.changes.prev_values[ref] = pre_change_values
        self.changes.prev_reprs[ref] = str(instance)
        self.changes.changes.append(UpdateObjectChange(
            obj=ref,
            fields=field_values
        ))
        from pprint import pprint
        pprint(self.changes)

    def handle_post_delete(self, sender: Type[Model], instance: Model, **kwargs):
        ref = self.reverse_ref_lookup(ObjectReference.simple_from_instance(instance))
        pre_change_values = self.pre_change_values.pop(ref, None)
        if pre_change_values:
            self.changes.prev_values[ref] = pre_change_values
        self.changes.prev_reprs[ref] = str(instance)
        self.changes.changes.append(DeleteObjectChange(
            obj=ref,
        ))
        from pprint import pprint
        pprint(self.changes)

    def handle_m2m_changed(self, sender: Type[Model], instance: Model, **kwargs):
        pass


def handle_pre_change_instance(sender: Type[Model], **kwargs):
    if sender._meta.app_label != 'mapdata':
        return
    manager: ChangesetOverlayManager = getattr(overlay_state, 'manager', None)
    if manager:
        manager.handle_pre_change_instance(sender=sender, **kwargs)


def handle_post_save(sender: Type[Model], **kwargs):
    if sender._meta.app_label != 'mapdata':
        return
    manager: ChangesetOverlayManager = getattr(overlay_state, 'manager', None)
    if manager:
        manager.handle_post_save(sender=sender, **kwargs)


def handle_post_delete(sender: Type[Model], **kwargs):
    if sender._meta.app_label != 'mapdata':
        return
    manager: ChangesetOverlayManager = getattr(overlay_state, 'manager', None)
    if manager:
        manager.handle_post_delete(sender=sender, **kwargs)


def handle_m2m_changed(sender: Type[Model], **kwargs):
    if sender._meta.app_label != 'mapdata':
        return
    manager: ChangesetOverlayManager = getattr(overlay_state, 'manager', None)
    if manager:
        manager.handle_m2m_changed(sender=sender, **kwargs)
