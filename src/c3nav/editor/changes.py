import datetime
import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TypeAlias, Literal, Annotated, Union, Type, Any

from django.core import serializers
from django.db import transaction
from django.db.models import Model
from django.db.models.fields.related import OneToOneField, ForeignKey, ManyToManyField
from django.utils import timezone
from pydantic import ConfigDict, Discriminator
from pydantic.fields import Field

from c3nav.api.schema import BaseSchema

try:
    from asgiref.local import Local as LocalContext
except ImportError:
    from threading import local as LocalContext


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


class UpdateManyToManyChange(BaseSchema):
    type: Literal["m2m_add"] = "m2m_update"
    field: str
    add_values: set[int] = set()
    remove_values: set[int] = set()


class ClearManyToManyChange(BaseSchema):
    type: Literal["m2m_clear"] = "m2m_clear"
    field: str


ChangeSetChange = Annotated[
    Union[
        CreateObjectChange,
        UpdateObjectChange,
        DeleteObjectChange,
        UpdateManyToManyChange,
        ClearManyToManyChange,
    ],
    Discriminator("type"),
]


class ChangeSetChanges(BaseSchema):
    prev_reprs: dict[ObjectReference, str] = {}
    prev_values: dict[ObjectReference, FieldValuesDict] = {}
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
    new_changes: list[ChangeSetChange] = field(default_factory=list)
    pre_change_values: dict[ObjectReference, FieldValuesDict] = field(default_factory=dict)

    @staticmethod
    def get_model_field_values(instance: Model) -> FieldValuesDict:
        return json.loads(serializers.serialize("json", [instance]))[0]["fields"]

    def get_ref_and_pre_change_values(self, instance: Model) -> ObjectReference:
        ref = ObjectReference.from_instance(instance)

        pre_change_values = self.pre_change_values.pop(ref, None)
        if pre_change_values:
            self.changes.prev_values[ref] = pre_change_values
        self.changes.prev_reprs[ref] = str(instance)

        return ref

    def handle_pre_change_instance(self, instance: Model, **kwargs):
        if instance.pk is None:
            return
        ref = ObjectReference.from_instance(instance)
        if ref not in self.pre_change_values and ref not in self.changes.prev_values:
            self.pre_change_values[ref] = self.get_model_field_values(
                instance._meta.model.objects.get(pk=instance.pk)
            )

    def handle_post_save(self, instance: Model, created: bool, update_fields: set | None, **kwargs):
        field_values = self.get_model_field_values(instance)

        ref = self.get_ref_and_pre_change_values(instance)

        if created:
            self.new_changes.append(CreateObjectChange(obj=ref, fields=field_values))
            return

        if update_fields:
            field_values = {name: value for name, value in field_values.items() if name in update_fields}

        self.new_changes.append(UpdateObjectChange(obj=ref, fields=field_values))

    def handle_post_delete(self, instance: Model, **kwargs):
        ref = self.get_ref_and_pre_change_values(instance)
        self.new_changes.append(DeleteObjectChange(obj=ref))

    def handle_m2m_changed(self, sender: Type[Model], instance: Model, action: str, model: Type[Model],
                           pk_set: set | None, reverse: bool, **kwargs):
        if reverse:
            raise NotImplementedError

        if action.startswith("pre_"):
            return self.handle_pre_change_instance(sender=instance._meta.model, instance=instance)

        for field in instance._meta.get_fields():
            if isinstance(field, ManyToManyField):
                # todo: actually identify field!!
                raise NotImplementedError
                break
        else:
            raise ValueError

        ref = self.get_ref_and_pre_change_values(instance)

        if action == "post_clear":
            self.new_changes.append(ClearManyToManyChange(obj=ref, field=field.name))
            return

        if self.new_changes:
            last_change = self.new_changes[-1]
            if isinstance(last_change, UpdateManyToManyChange) and last_change == ref and last_change == field.name:
                if action == "post_add":
                    last_change.add_values.update(pk_set)
                    last_change.remove_values.difference_update(pk_set)
                else:
                    last_change.add_values.difference_update(pk_set)
                    last_change.remove_values.update(pk_set)
                return

        if action == "post_add":
            self.new_changes.append(UpdateManyToManyChange(obj=ref, field=field.name, add_values=list(pk_set)))
        else:
            self.new_changes.append(UpdateManyToManyChange(obj=ref, field=field.name, remove_values=list(pk_set)))


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
