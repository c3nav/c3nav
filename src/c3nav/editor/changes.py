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

    def get_model_field_values(self, instance: Model) -> FieldValuesDict:
        return json.loads(serializers.serialize("json", [instance]))[0]["fields"]

    def handle_pre_change_instance(self, sender: Type[Model], instance: Model, **kwargs):
        if instance.pk is None:
            return
        ref = ObjectReference.from_instance(instance)
        if ref not in self.pre_change_values and ref not in self.changes.prev_values:
            self.pre_change_values[ref] = self.get_model_field_values(
                instance._meta.model.objects.get(pk=instance.pk)
            )

    def handle_post_save(self, sender: Type[Model], instance: Model, created: bool,
                         update_fields: set | None, **kwargs):
        field_values = self.get_model_field_values(instance)

        ref = ObjectReference.from_instance(instance)

        if created:
            self.changes.changes.append(CreateObjectChange(obj=ref, fields=field_values))
            from pprint import pprint
            pprint(self.changes)
            return

        if update_fields:
            field_values = {name: value for name, value in field_values.items() if name in update_fields}

        pre_change_values = self.pre_change_values.pop(ref, None)
        if pre_change_values:
            self.changes.prev_values[ref] = pre_change_values
        self.changes.prev_reprs[ref] = str(instance)
        self.changes.changes.append(UpdateObjectChange(obj=ref, fields=field_values))
        from pprint import pprint
        pprint(self.changes)

    def handle_post_delete(self, sender: Type[Model], instance: Model, **kwargs):
        ref = ObjectReference.from_instance(instance)
        pre_change_values = self.pre_change_values.pop(ref, None)
        if pre_change_values:
            self.changes.prev_values[ref] = pre_change_values
        self.changes.prev_reprs[ref] = str(instance)
        self.changes.changes.append(DeleteObjectChange(
            obj=ref,
        ))
        from pprint import pprint
        pprint(self.changes)

    def handle_m2m_changed(self, sender: Type[Model], instance: Model, action: str, model: Type[Model],
                           pk_set: set | None, reverse: bool, **kwargs):
        if reverse:
            raise NotImplementedError

        if action.startswith("pre_"):
            return self.handle_pre_change_instance(sender=instance._meta.model, instance=instance)

        for field in instance._meta.get_fields():
            if isinstance(field, ManyToManyField):
                break
        else:
            raise ValueError

        ref = ObjectReference.from_instance(instance)
        pre_change_values = self.pre_change_values.pop(ref, None)
        if pre_change_values:
            self.changes.prev_values[ref] = pre_change_values

        match(action):
            case "post_add":
                self.changes.changes.append(AddManyToManyChange(
                    obj=ref,
                    field=field.name,
                    values=list(pk_set),
                ))

            case "post_remove":
                self.changes.changes.append(RemoveManyToManyChange(
                    obj=ref,
                    field=field.name,
                    values=list(pk_set),
                ))

            case "post_clear":
                self.changes.changes.append(ClearManyToManyChange(
                    obj=ref,
                    field=field.name,
                ))

        from pprint import pprint
        pprint(self.changes)


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
