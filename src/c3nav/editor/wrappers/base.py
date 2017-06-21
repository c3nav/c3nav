from functools import wraps

from django.db import models
from django.db.models import Manager


class BaseWrapper:
    _not_wrapped = ('_changeset', '_author', '_obj', '_created_pks', '_result', '_extra', '_result_cache',
                    '_initial_values')
    _allowed_callables = ()
    _wrapped_callables = ()

    def __init__(self, changeset, obj, author=None):
        self._changeset = changeset
        self._author = author
        self._obj = obj

    # noinspection PyUnresolvedReferences
    def _wrap_model(self, model):
        from c3nav.editor.wrappers.instance import ModelInstanceWrapper
        from c3nav.editor.wrappers.model import ModelWrapper
        if isinstance(model, type) and issubclass(model, ModelInstanceWrapper):
            model = model._parent
        if isinstance(model, ModelWrapper):
            if self._author == model._author and self._changeset == model._changeset:
                return model
            model = model._obj
        assert issubclass(model, models.Model)
        return ModelWrapper(self._changeset, model, self._author)

    def _wrap_instance(self, instance):
        from c3nav.editor.wrappers.instance import ModelInstanceWrapper
        if isinstance(instance, ModelInstanceWrapper):
            if self._author == instance._author and self._changeset == instance._changeset:
                return instance
            instance = instance._obj
        assert isinstance(instance, models.Model)
        return self._wrap_model(type(instance)).create_wrapped_model_class()(self._changeset, instance, self._author)

    def _wrap_manager(self, manager):
        from c3nav.editor.wrappers.manager import ManagerWrapper, ManyRelatedManagerWrapper, RelatedManagerWrapper
        assert isinstance(manager, Manager)
        if hasattr(manager, 'through'):
            return ManyRelatedManagerWrapper(self._changeset, manager, self._author)
        if hasattr(manager, 'instance'):
            return RelatedManagerWrapper(self._changeset, manager, self._author)
        return ManagerWrapper(self._changeset, manager, self._author)

    def _wrap_queryset(self, queryset):
        from c3nav.editor.wrappers.query import QuerySetWrapper
        return QuerySetWrapper(self._changeset, queryset, self._author)

    def __getattr__(self, name):
        from c3nav.editor.wrappers.instance import ModelInstanceWrapper
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
            if name in self._wrapped_callables:
                func = getattr(self._obj.__class__, name)

                @wraps(func)
                def wrapper(*args, **kwargs):
                    return func(self, *args, **kwargs)
                return wrapper
            if isinstance(self, ModelInstanceWrapper) and not hasattr(models.Model, name):
                return value
            raise TypeError('Can not call %s.%s wrapped!' % (type(self), name))
        return value

    def __setattr__(self, name, value):
        if name in self._not_wrapped:
            return super().__setattr__(name, value)
        return setattr(self._obj, name, value)

    def __delattr__(self, name):
        return delattr(self._obj, name)
