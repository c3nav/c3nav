from django.db import models
from django.db.models import Manager
from django.db.models.fields.related_descriptors import ForwardManyToOneDescriptor


class BaseWrapper:
    _not_wrapped = ('_changeset', '_author', '_obj', '_changes_qs', '_initial_values')
    _allowed_callables = ('', )

    def __init__(self, changeset, obj, author=None):
        self._changeset = changeset
        self._author = author
        self._obj = obj

    def _wrap_model(self, model):
        return ModelWrapper(self._changeset, model, self._author)

    def _wrap_instance(self, instance):
        return ModelInstanceWrapper(self._changeset, instance, self._author)

    def _wrap_manager(self, manager):
        return ManagerWrapper(self._changeset, manager, self._author)

    def _wrap_queryset(self, queryset):
        return QuerySetWrapper(self._changeset, queryset, self._author)

    def __getattr__(self, name):
        value = getattr(self._obj, name)
        if isinstance(value, Manager):
            value = self._wrap_manager(value)
        elif isinstance(value, type) and issubclass(value, models.Model) and value._meta.app_label == 'mapdata':
            value = self._wrap_model(value)
        elif isinstance(value, models.Model) and value._meta.app_label == 'mapdata':
            value = self._wrap_instance(value)
        elif isinstance(value, type) and issubclass(value, Exception):
            pass
        elif callable(value) and name not in self._allowed_callables:
            if not isinstance(self, ModelInstanceWrapper) or hasattr(models.Model, name):
                raise TypeError('Can not call %s.%s wrapped!' % (self._obj, name))

        # print(self._obj, name, type(value), value)
        return value

    def __setattr__(self, name, value):
        if name in self._not_wrapped:
            return super().__setattr__(name, value)
        return setattr(self._obj, name, value)

    def __delattr__(self, name):
        return delattr(self._obj, name)


class ModelWrapper(BaseWrapper):
    _allowed_callables = ('EditorForm', )

    def __eq__(self, other):
        if type(other) == ModelWrapper:
            return self._obj is other._obj
        return self._obj is other

    def __call__(self, **kwargs):
        instance = self._wrap_instance(self._obj())
        for name, value in kwargs.items():
            setattr(instance, name, value)
        return instance


class ModelInstanceWrapper(BaseWrapper):
    _allowed_callables = ('full_clean', 'validate_unique')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._initial_values = {}
        for field in self._obj._meta.get_fields():
            if field.related_model is None:
                if field.primary_key:
                    continue
                self._initial_values[field] = getattr(self, field.name)
            elif (field.many_to_one or field.one_to_one) and not field.primary_key:
                self._initial_values[field] = getattr(self, field.name).pk

    def __eq__(self, other):
        if type(other) == ModelWrapper:
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
        elif isinstance(self.pk, int):
            return '<%s #%d (existing) with Changeset #%d>' % (cls_name, self.pk, self._changeset.pk)
        elif isinstance(self.pk, str):
            return '<%s #%s (created) from Changeset #%d>' % (cls_name, self.pk, self._changeset.pk)
        raise TypeError

    def save(self, author=None):
        if author is None:
            author = self._author
        if self.pk is None:
            self._changeset.add_create(self, author=author)
        for field, initial_value in self._initial_values.items():
            new_value = getattr(self._obj, field.name)
            if field.related_model:
                if new_value.pk != initial_value.pk:
                    self._changeset.add_update(self, name=field.name, value=new_value.pk, author=author)
                continue

            if new_value == initial_value:
                continue

            if field.name == 'titles':
                for lang in (set(initial_value.keys()) | set(new_value.keys())):
                    new_title = new_value.get(lang, '')
                    if new_title != initial_value.get(lang, ''):
                        self._changeset.add_update(self, name='title_'+lang, value=new_title, author=author)
                continue

            self._changeset.add_update(self, name=field.name, value=new_value, author=author)

    def delete(self, author=None):
        if author is None:
            author = self._author
        self._changeset.add_delete(self, author=author)


class ChangesQuerySet():
    def __init__(self, changeset, model, author):
        self._changeset = changeset
        self._model = model
        self._author = author


class BaseQueryWrapper(BaseWrapper):
    def __init__(self, changeset, obj, author=None, changes_qs=None):
        super().__init__(changeset, obj, author)
        if changes_qs is None:
            changes_qs = ChangesQuerySet(changeset, obj.model, author)
        self._changes_qs = changes_qs

    def _wrap_queryset(self, queryset, changes_qs=None):
        if changes_qs is None:
            changes_qs = self._changes_qs
        return QuerySetWrapper(self._changeset, queryset, self._author, changes_qs)

    def all(self):
        return self._wrap_queryset(self._obj.all())

    def none(self):
        return self._wrap_queryset(self._obj.none())

    def select_related(self, *args, **kwargs):
        return self._wrap_queryset(self._obj.select_related(*args, **kwargs))

    def prefetch_related(self, *args, **kwargs):
        return self._wrap_queryset(self._obj.prefetch_related(*args, **kwargs))

    def get(self, **kwargs):
        return self._wrap_instance(self._obj.get(**kwargs))

    def order_by(self, *args):
        return self._wrap_queryset(self._obj.order_by(*args))

    def filter(self, *args, **kwargs):
        kwargs = {name: (value._obj if isinstance(value, ModelInstanceWrapper) else value)
                  for name, value in kwargs.items()}
        kwargs = {name: (((item._obj if isinstance(item, ModelInstanceWrapper) else item) for item in value)
                         if name.endswith('__in') else value)
                  for name, value in kwargs.items()}
        return self._wrap_queryset(self._obj.filter(*args, **kwargs))

    def count(self):
        return self._obj.count()

    def values_list(self, *args, flat=False):
        return self._obj.values_list(*args, flat=flat)

    def first(self):
        first = self._obj.first()
        if first is not None:
            first = self._wrap_instance(first)
        return first

    def __iter__(self):
        return iter([instance for instance in self._obj])

    def iterator(self):
        return iter(self)

    def __len__(self):
        return len(self._obj)


class ManagerWrapper(BaseQueryWrapper):
    pass


class QuerySetWrapper(BaseQueryWrapper):
    pass
