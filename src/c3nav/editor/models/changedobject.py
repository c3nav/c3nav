import typing
from itertools import chain

from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import ugettext_lazy as _

from c3nav.editor.utils import is_created_pk
from c3nav.editor.wrappers import ModelInstanceWrapper
from c3nav.mapdata.fields import JSONField


class ChangedObject(models.Model):
    changeset = models.ForeignKey('editor.ChangeSet', on_delete=models.CASCADE, verbose_name=_('Change Set'))
    created = models.DateTimeField(auto_now_add=True, verbose_name=_('created'))
    last_update = models.DateTimeField(auto_now=True, verbose_name=_('last update'))
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    existing_object_pk = models.PositiveIntegerField(null=True, verbose_name=_('id of existing object'))
    updated_fields = JSONField(default={}, verbose_name=_('updated fields'))
    m2m_added = JSONField(default={}, verbose_name=_('added m2m values'))
    m2m_removed = JSONField(default={}, verbose_name=_('removed m2m values'))
    deleted = models.BooleanField(default=False, verbose_name=_('new field value'))

    class Meta:
        verbose_name = _('Changed object')
        verbose_name_plural = _('Changed objects')
        default_related_name = 'changed_objects_set'
        unique_together = ('changeset', 'content_type', 'existing_object_pk')
        ordering = ['created', 'pk']

    def __init__(self, *args, **kwargs):
        model_class = kwargs.pop('model_class', None)
        super().__init__(*args, **kwargs)
        self._set_object = None
        self._m2m_added_cache = {name: set(values) for name, values in self.m2m_added}
        self._m2m_removed_cache = {name: set(values) for name, values in self.m2m_added}
        if model_class is not None:
            self.model_class = model_class

    @property
    def model_class(self) -> typing.Optional[typing.Type[models.Model]]:
        return self.content_type.model_class()

    @model_class.setter
    def model_class(self, value: typing.Optional[typing.Type[models.Model]]):
        self.content_type = ContentType.objects.get_for_model(value)

    @property
    def obj_pk(self) -> typing.Union[int, str]:
        if not self.is_created:
            return self.existing_object_pk
        return 'c'+str(self.pk)

    @property
    def obj(self) -> ModelInstanceWrapper:
        return self.get_obj(get_foreign_objects=True)

    @property
    def is_created(self):
        return self.existing_object_pk is None

    def get_obj(self, get_foreign_objects=False) -> ModelInstanceWrapper:
        model = self.model_class

        if not self.is_created:
            if self._set_object is None:
                self._set_object = self.changeset.wrap_instance(model.objects.get(pk=self.existing_object_pk))

            # noinspection PyTypeChecker
            return self._set_object

        pk = self.obj_pk

        obj = model()
        obj.pk = pk
        if hasattr(model._meta.pk, 'related_model'):
            setattr(obj, model._meta.pk.related_model._meta.pk.attname, pk)
        obj._state.adding = False

        for name, value in self.updated_fields.items():
            if name.startswith('title_'):
                if value:
                    obj.titles[name[6:]] = value
                continue

            field = model._meta.get_field(name)

            if field.many_to_many:
                continue

            if field.many_to_one:
                setattr(obj, field.attname, value)
                if is_created_pk(value):
                    setattr(obj, field.get_cache_name(), self.changeset.get_created_object(field.related_model, value))
                elif get_foreign_objects:
                    related_obj = self.changeset.wrap_model(field.related_model).objects.get(pk=value)
                    setattr(obj, field.get_cache_name(), related_obj)
                continue

            setattr(obj, name, field.to_python(value))
        return self.changeset.wrap_instance(obj)

    def add_relevant_object_pks(self, object_pks):
        object_pks.setdefault(self.model_class, set()).add(self.obj_pk)
        for name, value in self.updated_fields.items():
            if name.startswith('title_'):
                continue
            field = self.model_class._meta.get_field(name)
            if field.is_relation:
                object_pks.setdefault(field.related_model, set()).add(value)

        for name, value in chain(self._m2m_added_cache.items(), self._m2m_removed_cache.items()):
            field = self.model_class._meta.get_field(name)
            object_pks.setdefault(field.related_model, set()).update(value)

    def update_changeset_cache(self):
        if self.pk is None:
            return

        model = self.model_class
        pk = self.obj_pk

        self.changeset.changed_objects.setdefault(model, {})[pk] = self

        if self.is_created:
            if not self.deleted:
                self.changeset.created_objects.setdefault(model, {})[pk] = self.updated_fields
            self.changeset.ever_created_objects.setdefault(model, {})[pk] = self.updated_fields
        else:
            if not self.deleted:
                self.changeset.updated_existing.setdefault(model, {})[pk] = self.updated_fields
                self.changeset.deleted_existing.setdefault(model, set()).discard(pk)
            else:
                self.changeset.updated_existing.setdefault(model, {}).pop(pk, None)
                self.changeset.deleted_existing.setdefault(model, set()).add(pk)

        if not self.deleted:
            self.changeset.m2m_added.get(model, {})[pk] = self._m2m_added_cache
            self.changeset.m2m_removed.get(model, {})[pk] = self._m2m_removed_cache
        else:
            self.changeset.m2m_added.get(model, {}).pop(pk, None)
            self.changeset.m2m_removed.get(model, {}).pop(pk, None)

    def save(self, *args, **kwargs):
        self.m2m_added = {name: tuple(values) for name, values in self._m2m_added_cache}
        self.m2m_removed = {name: tuple(values) for name, values in self._m2m_added_cache}
        if self.changeset.proposed is not None or self.changeset.applied is not None:
            raise TypeError('can not add change object to uneditable changeset.')
        super().save(*args, **kwargs)
        if not self.changeset.fill_changes_cache():
            self.update_changeset_cache()

    def delete(self, *args, **kwargs):
        raise TypeError('change objects can not be deleted directly.')

    def __repr__(self):
        return '<ChangedObject #%s on ChangeSet #%s>' % (str(self.pk), str(self.changeset_id))
