from collections import deque

from django.db import models
from django.db.models import Manager, Prefetch
from django.db.models.fields.related_descriptors import ForwardManyToOneDescriptor


class BaseWrapper:
    _not_wrapped = ('_changeset', '_author', '_obj', '_changes_qs', '_initial_values')
    _allowed_callables = ('', )

    def __init__(self, changeset, obj, author=None):
        self._changeset = changeset
        self._author = author
        self._obj = obj

    def _wrap_model(self, model):
        assert issubclass(model, models.Model)
        return ModelWrapper(self._changeset, model, self._author)

    def _wrap_instance(self, instance):
        if isinstance(instance, ModelInstanceWrapper):
            if self._author == instance._author and self._changeset == instance._changeset:
                return instance
            instance = instance._obj
        assert isinstance(instance, models.Model)
        return self._wrap_model(type(instance)).create_wrapped_model_class()(self._changeset, instance, self._author)

    def _wrap_manager(self, manager):
        assert isinstance(manager, Manager)
        if hasattr(manager, 'through'):
            return ManyRelatedManagerWrapper(self._changeset, manager, self._author)
        if hasattr(manager, 'instance'):
            return RelatedManagerWrapper(self._changeset, manager, self._author)
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
        return value

    def __setattr__(self, name, value):
        if name in self._not_wrapped:
            return super().__setattr__(name, value)
        return setattr(self._obj, name, value)

    def __delattr__(self, name):
        return delattr(self._obj, name)


class ModelWrapper(BaseWrapper):
    _allowed_callables = ('EditorForm',)

    def __eq__(self, other):
        if type(other) == ModelWrapper:
            return self._obj is other._obj
        return self._obj is other

    def create_wrapped_model_class(self):
        return self.create_metaclass()(self._obj.__name__ + 'InstanceWrapper', (ModelInstanceWrapper,), {})

    def __call__(self, **kwargs):
        instance = self._wrap_instance(self._obj())
        for name, value in kwargs.items():
            setattr(instance, name, value)
        return instance

    def create_metaclass(self):
        parent = self

        class ModelInstanceWrapperMeta(type):
            def __getattr__(self, name):
                return getattr(parent, name)

            def __setattr__(self, name, value):
                setattr(parent, name, value)

            def __delattr__(self, name):
                delattr(parent, name)

        ModelInstanceWrapperMeta.__name__ = self._obj.__name__+'InstanceWrapperMeta'

        return ModelInstanceWrapperMeta


class ModelInstanceWrapper(BaseWrapper):
    _allowed_callables = ('full_clean', 'validate_unique')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        updates = self._changeset.updated_values.get(type(self._obj), {}).get(self._obj.pk, {})
        self._initial_values = {}
        for field in self._obj._meta.get_fields():
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
                    setattr(self._obj, field.name, updates[field.name])
                self._initial_values[field] = getattr(self._obj, field.name)
            elif (field.many_to_one or field.one_to_one) and not field.primary_key:
                if field.name in updates:
                    self._wrap_model(field.model).get(pk=updates[field.name])
                self._initial_values[field] = getattr(self._obj, field.name)

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
                new_pk = None if new_value is None else new_value.pk
                initial_pk = None if initial_value is None else initial_value.pk
                if new_pk != initial_pk:
                    self._changeset.add_update(self, name=field.name, value=new_pk, author=author)
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


class ChangesQuerySet:
    def __init__(self, changeset, model, author):
        self._changeset = changeset
        self._model = model
        self._author = author


class BaseQueryWrapper(BaseWrapper):
    _allowed_callables = ('_add_hints', '_next_is_sticky', 'get_prefetch_queryset')

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

    def prefetch_related(self, *lookups):
        new_lookups = deque()
        for lookup in lookups:
            if not isinstance(lookup, str):
                new_lookups.append(lookup)
                continue
            model = self._obj.model
            for name in lookup.split('__'):
                model = model._meta.get_field(name).related_model
            new_lookups.append(Prefetch(lookup, self._wrap_model(model).objects.all()._obj))
        return self._wrap_queryset(self._obj.prefetch_related(*new_lookups))

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

    def using(self, alias):
        return self._wrap_queryset(self._obj.using(alias))

    def __iter__(self):
        return iter([self._wrap_instance(instance) for instance in self._obj])

    def iterator(self):
        return iter(self)

    def __len__(self):
        return len(self._obj)


class ManagerWrapper(BaseQueryWrapper):
    def all(self):
        return self._wrap_queryset(self._obj.exclude(pk__in=self._changeset.deleted_existing.get(self._obj.model, ())))


class RelatedManagerWrapper(ManagerWrapper):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _get_cache_name(self):
        return self._obj.field.related_query_name()

    def all(self):
        result = self.instance._prefetched_objects_cache.get(self._get_cache_name(), None)
        if result is not None:
            return result
        super().all()


class ManyRelatedManagerWrapper(RelatedManagerWrapper):
    def _check_through(self):
        if not self._obj.through._meta.auto_created:
            raise AttributeError('Cannot do this an a ManyToManyField which specifies an intermediary model.')

    def _get_cache_name(self):
        return self._obj.prefetch_cache_name

    def set(self, objs, author=None):
        if author is None:
            author = self._author

        old_ids = set(self.values_list('pk', flat=True))
        new_ids = set(obj.pk for obj in objs)

        self.remove(*(old_ids - new_ids), author=author)
        self.add(*(new_ids - old_ids), author=author)

    def add(self, *objs, author=None):
        if author is None:
            author = self._author

        for obj in objs:
            pk = (obj.pk if isinstance(obj, self._obj.model) else obj)
            self._changeset.add_m2m_add(self._obj.instance, name=self._get_cache_name(), value=pk, author=author)

    def remove(self, *objs, author=None):
        if author is None:
            author = self._author

        for obj in objs:
            pk = (obj.pk if isinstance(obj, self._obj.model) else obj)
            self._changeset.add_m2m_remove(self._obj.instance, name=self._get_cache_name(), value=pk, author=author)


class QuerySetWrapper(BaseQueryWrapper):
    @property
    def _iterable_class(self):
        return self._obj._iterable_class
