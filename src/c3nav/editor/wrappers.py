from django.db import models
from django.db.models import Manager


class BaseWrapper:
    _not_wrapped = ('_changeset', '_author', '_obj', '_changes_qs')
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
        instance = self._wrap_instance(self._value())
        for name, value in kwargs.items():
            setattr(instance, name, value)
        return instance


class ModelInstanceWrapper(BaseWrapper):
    def __eq__(self, other):
        if type(other) == ModelWrapper:
            if type(self._obj) is not type(other._obj):  # noqa
                return False
        elif type(self._obj) is not type(other):
            return False
        return self.pk == other.pk


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
        return self._wrap_queryset(self._obj.filter(*args, **kwargs))

    def count(self):
        return self._obj.count()

    def values_list(self, *args, flat=False):
        return self._obj.values_list(*args, flat=flat)

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
