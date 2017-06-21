from django.db import models
from django.db.models import Field
from django.db.models.fields.related_descriptors import ForwardManyToOneDescriptor

from c3nav.editor.utils import is_created_pk
from c3nav.editor.wrappers import BaseWrapper


class ModelInstanceWrapper(BaseWrapper):
    _allowed_callables = ('full_clean', '_perform_unique_checks', '_perform_date_checks')
    _wrapped_callables = ('validate_unique', '_get_pk_val')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        updates = self._changeset.updated_existing.get(type(self._obj), {}).get(self._obj.pk, {})
        self._initial_values = {}
        for field in self._obj._meta.get_fields():
            if not isinstance(field, Field):
                continue
            if field.related_model is None:
                if field.primary_key:
                    continue

                if field.name == 'titles':
                    for name, value in updates.items():
                        if not name.startswith('title_'):
                            continue
                        if not value:
                            self._obj.titles.pop(name[6:], None)
                        else:
                            self._obj.titles[name[6:]] = value
                elif field.name in updates:
                    setattr(self._obj, field.name, field.to_python(updates[field.name]))
                self._initial_values[field] = getattr(self._obj, field.name)
            elif (field.many_to_one or field.one_to_one) and not field.primary_key:
                if field.name in updates:
                    value_pk = updates[field.name]
                    class_value = getattr(type(self._obj), field.name, None)
                    if is_created_pk(value_pk):
                        obj = self._wrap_model(field.model).get(pk=value_pk)
                        setattr(self._obj, class_value.cache_name, obj)
                        setattr(self._obj, field.attname, obj.pk)
                    else:
                        delattr(self._obj, class_value.cache_name)
                        setattr(self._obj, field.attname, value_pk)
                self._initial_values[field] = getattr(self._obj, field.attname)

    def __eq__(self, other):
        if isinstance(other, BaseWrapper):
            if type(self._obj) is not type(other._obj):  # noqa
                return False
        elif type(self._obj) is not type(other):
            return False
        return self.pk == other.pk

    def __setattr__(self, name, value):
        if name in self._not_wrapped:
            return super().__setattr__(name, value)
        class_value = getattr(type(self._obj), name, None)
        if isinstance(class_value, ForwardManyToOneDescriptor) and value is not None:
            if isinstance(value, models.Model):
                value = self._wrap_instance(value)
            if not isinstance(value, ModelInstanceWrapper):
                raise ValueError('value has to be None or ModelInstanceWrapper')
            setattr(self._obj, name, value._obj)
            setattr(self._obj, class_value.cache_name, value)
            return
        super().__setattr__(name, value)

    def __repr__(self):
        cls_name = self._obj.__class__.__name__
        if self.pk is None:
            return '<%s (unsaved) with Changeset #%d>' % (cls_name, self._changeset.pk)
        elif is_created_pk(self.pk):
            return '<%s #%s (created) from Changeset #%d>' % (cls_name, self.pk, self._changeset.pk)
        return '<%s #%d (existing) with Changeset #%d>' % (cls_name, self.pk, self._changeset.pk)

    def _get_unique_checks(self, exclude=None):
        unique_checks, date_checks = self._obj.__class__._get_unique_checks(self, exclude=exclude)
        return [(self._wrap_model(model), unique) for model, unique in unique_checks], date_checks

    def save(self, author=None):
        if author is None:
            author = self._author
        if self.pk is None:
            self._changeset.add_create(self, author=author)
        for field, initial_value in self._initial_values.items():
            class_value = getattr(type(self._obj), field.name, None)
            if isinstance(class_value, ForwardManyToOneDescriptor):
                try:
                    new_value = getattr(self._obj, class_value.cache_name)
                except AttributeError:
                    new_value = getattr(self._obj, field.attname)
                else:
                    new_value = None if new_value is None else new_value.pk

                if new_value != initial_value:
                    self._changeset.add_update(self, name=field.name, value=new_value, author=author)
                continue

            new_value = getattr(self._obj, field.name)
            if new_value == initial_value:
                continue

            if field.name == 'titles':
                for lang in (set(initial_value.keys()) | set(new_value.keys())):
                    new_title = new_value.get(lang, '')
                    if new_title != initial_value.get(lang, ''):
                        self._changeset.add_update(self, name='title_'+lang, value=new_title, author=author)
                continue

            self._changeset.add_update(self, name=field.name, value=field.get_prep_value(new_value), author=author)

    def delete(self, author=None):
        if author is None:
            author = self._author
        self._changeset.add_delete(self, author=author)
