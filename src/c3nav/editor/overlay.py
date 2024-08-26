import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Type

from django.core import serializers
from django.db import transaction
from django.db.models import Model
from django.db.models.fields.related import ManyToManyField

from c3nav.editor.operations import DatabaseOperation, ObjectReference, FieldValuesDict, CreateObjectOperation, \
    UpdateObjectOperation, DeleteObjectOperation, ClearManyToManyOperation, UpdateManyToManyOperation, CollectedChanges

try:
    from asgiref.local import Local as LocalContext
except ImportError:
    from threading import local as LocalContext


overlay_state = LocalContext()


class InterceptAbortTransaction(Exception):
    pass


@dataclass
class DatabaseOverlayManager:
    changes: CollectedChanges
    new_operations: list[DatabaseOperation] = field(default_factory=list)
    pre_change_values: dict[ObjectReference, FieldValuesDict] = field(default_factory=dict)

    @classmethod
    @contextmanager
    def enable(cls, changes: CollectedChanges | None, commit: bool):
        if getattr(overlay_state, 'manager', None) is not None:
            raise TypeError
        if changes is None:
            changes = CollectedChanges()
        try:
            with transaction.atomic():
                manager = DatabaseOverlayManager(changes)
                manager.changes.prefetch().apply()
                overlay_state.manager = manager
                yield manager
                if not commit:
                    raise InterceptAbortTransaction
        except InterceptAbortTransaction:
            pass
        finally:
            overlay_state.manager = None

    def save_new_operations(self):
        self.changes.operations.extend(self.new_operations)

    @staticmethod
    def get_model_field_values(instance: Model) -> FieldValuesDict:
        return json.loads(serializers.serialize("json", [instance]))[0]["fields"]

    def get_ref_and_pre_change_values(self, instance: Model) -> ObjectReference:
        ref = ObjectReference.from_instance(instance)

        pre_change_values = self.pre_change_values.pop(ref, None)
        if pre_change_values:
            self.changes.prev_values.setdefault(ref.model, {})[ref.id] = pre_change_values
        self.changes.prev_reprs.setdefault(ref.model, {})[ref.id] = str(instance)

        return ref

    def handle_pre_change_instance(self, instance: Model, **kwargs):
        if instance.pk is None:
            return
        ref = ObjectReference.from_instance(instance)
        if ref not in self.pre_change_values and ref.id not in self.changes.prev_values.get(ref.model, {}):
            self.pre_change_values[ref] = self.get_model_field_values(
                instance._meta.model.objects.get(pk=instance.pk)
            )

    def handle_post_save(self, instance: Model, created: bool, update_fields: set | None, **kwargs):
        field_values = self.get_model_field_values(instance)

        ref = self.get_ref_and_pre_change_values(instance)

        if created:
            self.new_operations.append(CreateObjectOperation(obj=ref, fields=field_values))
            return

        if update_fields:
            field_values = {name: value for name, value in field_values.items() if name in update_fields}

        self.new_operations.append(UpdateObjectOperation(obj=ref, fields=field_values))

    def handle_post_delete(self, instance: Model, **kwargs):
        ref = self.get_ref_and_pre_change_values(instance)
        self.new_operations.append(DeleteObjectOperation(obj=ref))

    def handle_m2m_changed(self, sender: Type[Model], instance: Model, action: str, model: Type[Model],
                           pk_set: set | None, reverse: bool, **kwargs):
        if reverse:
            raise NotImplementedError

        if action.startswith("pre_"):
            return self.handle_pre_change_instance(sender=instance._meta.model, instance=instance)

        for field in instance._meta.get_fields():
            if isinstance(field, ManyToManyField) and field.remote_field.through == sender:
                break
        else:
            raise ValueError

        ref = self.get_ref_and_pre_change_values(instance)

        if action == "post_clear":
            self.new_operations.append(ClearManyToManyOperation(obj=ref, field=field.name))
            return

        if self.new_operations:
            last_change = self.new_operations[-1]
            if isinstance(last_change, UpdateManyToManyOperation) and last_change == ref and last_change == field.name:
                if action == "post_add":
                    last_change.add_values.update(pk_set)
                    last_change.remove_values.difference_update(pk_set)
                else:
                    last_change.add_values.difference_update(pk_set)
                    last_change.remove_values.update(pk_set)
                return

        if action == "post_add":
            self.new_operations.append(UpdateManyToManyOperation(obj=ref, field=field.name, add_values=list(pk_set)))
        else:
            self.new_operations.append(UpdateManyToManyOperation(obj=ref, field=field.name, remove_values=list(pk_set)))


def handle_pre_change_instance(sender: Type[Model], **kwargs):
    if sender._meta.app_label != 'mapdata':
        return
    manager: DatabaseOverlayManager = getattr(overlay_state, 'manager', None)
    if manager:
        manager.handle_pre_change_instance(sender=sender, **kwargs)


def handle_post_save(sender: Type[Model], **kwargs):
    if sender._meta.app_label != 'mapdata':
        return
    manager: DatabaseOverlayManager = getattr(overlay_state, 'manager', None)
    if manager:
        manager.handle_post_save(sender=sender, **kwargs)


def handle_post_delete(sender: Type[Model], **kwargs):
    if sender._meta.app_label != 'mapdata':
        return
    manager: DatabaseOverlayManager = getattr(overlay_state, 'manager', None)
    if manager:
        manager.handle_post_delete(sender=sender, **kwargs)


def handle_m2m_changed(sender: Type[Model], **kwargs):
    if sender._meta.app_label != 'mapdata':
        return
    manager: DatabaseOverlayManager = getattr(overlay_state, 'manager', None)
    if manager:
        manager.handle_m2m_changed(sender=sender, **kwargs)
