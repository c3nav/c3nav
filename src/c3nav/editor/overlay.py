import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Type

from django.core import serializers
from django.db import transaction
from django.db.models import Model
from django.db.models.fields.related import ManyToManyField

from c3nav.editor.operations import CreateObjectOperation, \
    UpdateObjectOperation, DeleteObjectOperation, ClearManyToManyOperation, UpdateManyToManyOperation, \
    DatabaseOperationCollection, FieldValuesDict, ObjectReference
from c3nav.mapdata.fields import I18nField
from c3nav.mapdata.models import LocationSlug

try:
    from asgiref.local import Local as LocalContext
except ImportError:
    from threading import local as LocalContext


overlay_state = LocalContext()


class InterceptAbortTransaction(Exception):
    pass


@dataclass
class DatabaseOverlayManager:
    """
    This class handles the currently active database overlay and will apply and/or intercept changes.
    """
    operations: DatabaseOperationCollection = field(default_factory=DatabaseOperationCollection)
    pre_change_values: dict[ObjectReference, FieldValuesDict] = field(default_factory=dict, init=False, repr=False)

    @classmethod
    @contextmanager
    def enable(cls, operations: DatabaseOperationCollection | None = None, commit: bool = False):
        """
        Context manager to enable the database overlay, optionally <pre-applying the given changes.
        Only one overlay can be active at the same type, or else you get a TypeError.

        :param operations: what operations to pre-apply
        :param commit: whether to actually commit operations to the database or revert them at the end
        """
        if getattr(overlay_state, "manager", None) is not None:
            raise TypeError("Only one overlay can be active at the same time")
        if operations is None:
            operations = DatabaseOperationCollection()
        try:
            with transaction.atomic():
                manager = DatabaseOverlayManager(operations=DatabaseOperationCollection(prev=operations.prev))
                operations.prefetch().apply()
                overlay_state.manager = manager
                yield manager
                if not commit:
                    raise InterceptAbortTransaction
        except InterceptAbortTransaction:
            pass
        finally:
            overlay_state.manager = None

    @staticmethod
    def get_model_field_values(instance: Model) -> FieldValuesDict:
        values = json.loads(serializers.serialize("json", [instance]))[0]["fields"]
        if issubclass(instance._meta.model, LocationSlug):
            values["slug"] = instance.slug
        return values

    def get_ref_and_pre_change_values(self, instance: Model) -> tuple[ObjectReference, FieldValuesDict]:
        ref = ObjectReference.from_instance(instance)

        prev = self.operations.prev.get(ref)
        if prev is None:
            pre_change_values = self.pre_change_values.pop(ref)
            self.operations.prev.set(ref, values=pre_change_values, titles=getattr(instance, 'titles', None))
        else:
            pre_change_values = prev.values
        return ref, pre_change_values

    def handle_pre_change_instance(self, instance: Model, **kwargs):
        if instance.pk is None:
            return
        ref = ObjectReference.from_instance(instance)
        if ref not in self.pre_change_values and self.operations.prev.get(ref) is None:
            self.pre_change_values[ref] = self.get_model_field_values(
                instance._meta.model.objects.get(pk=instance.pk)
            )

    def handle_post_save(self, instance: Model, created: bool, update_fields: set | None, **kwargs):
        field_values = self.get_model_field_values(instance)

        if created:
            ref = ObjectReference.from_instance(instance)
            self.operations.append(CreateObjectOperation(obj=ref, fields=field_values))
            return

        ref, pre_change_values = self.get_ref_and_pre_change_values(instance)

        if update_fields:
            field_values = {name: value for name, value in field_values.items() if name in update_fields}

        if pre_change_values is not None:
            field_values = {name: value for name, value in field_values.items() if value != pre_change_values[name]}

            # special diffing within the i18n fields
            for field_name in tuple(field_values):
                if isinstance(instance._meta.get_field(field_name), I18nField):
                    before_val = pre_change_values[field_name]
                    after_val = field_values[field_name]

                    diff_val = {}
                    for lang in (set(before_val) | set(after_val)):
                        if before_val.get(lang, None) != after_val.get(lang, None):
                            diff_val[lang] = after_val.get(lang, None)
                    field_values[field_name] = diff_val

        self.operations.append(UpdateObjectOperation(obj=ref, fields=field_values))

    def handle_post_delete(self, instance: Model, **kwargs):
        # not isinstance() cause it would match submodels
        if instance._meta.model is LocationSlug:
            return
        ref, pre_change_values = self.get_ref_and_pre_change_values(instance)
        self.operations.append(DeleteObjectOperation(obj=ref))

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

        ref, pre_change_values = self.get_ref_and_pre_change_values(instance)

        if action == "post_clear":
            self.operations.append(ClearManyToManyOperation(obj=ref, field=field.name))
            return

        if self.operations:
            last_change = self.operations[-1]
            if (isinstance(last_change, UpdateManyToManyOperation)
                    and last_change.obj == ref and last_change == field.name):
                if action == "post_add":
                    last_change.add_values.update(pk_set)
                    last_change.remove_values.difference_update(pk_set)
                else:
                    last_change.add_values.difference_update(pk_set)
                    last_change.remove_values.update(pk_set)
                return

        if action == "post_add":
            self.operations.append(UpdateManyToManyOperation(obj=ref, field=field.name, add_values=list(pk_set)))
        else:
            self.operations.append(UpdateManyToManyOperation(obj=ref, field=field.name, remove_values=list(pk_set)))


def handle_pre_change_instance(sender: Type[Model], **kwargs):
    if sender._meta.app_label != 'mapdata':
        return
    if sender._meta.model_name == 'report':
        return
    manager: DatabaseOverlayManager = getattr(overlay_state, 'manager', None)
    if manager:
        manager.handle_pre_change_instance(sender=sender, **kwargs)


def handle_post_save(sender: Type[Model], **kwargs):
    if sender._meta.app_label != 'mapdata':
        return
    if sender._meta.model_name == 'report':
        return
    manager: DatabaseOverlayManager = getattr(overlay_state, 'manager', None)
    if manager:
        manager.handle_post_save(sender=sender, **kwargs)


def handle_post_delete(sender: Type[Model], **kwargs):
    if sender._meta.app_label != 'mapdata':
        return
    if sender._meta.model_name == 'report':
        return
    manager: DatabaseOverlayManager = getattr(overlay_state, 'manager', None)
    if manager:
        manager.handle_post_delete(sender=sender, **kwargs)


def handle_m2m_changed(sender: Type[Model], **kwargs):
    if sender._meta.app_label != 'mapdata':
        return
    if sender._meta.model_name == 'report':
        return
    manager: DatabaseOverlayManager = getattr(overlay_state, 'manager', None)
    if manager:
        manager.handle_m2m_changed(sender=sender, **kwargs)
