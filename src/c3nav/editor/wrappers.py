import typing
from collections import Iterable, deque
from functools import wraps
from itertools import chain

from django.db import models
from django.db.models import Manager, Prefetch, Q
from django.db.models.fields.related_descriptors import ForwardManyToOneDescriptor, ManyToManyDescriptor
from django.db.models.query_utils import DeferredAttribute


class BaseWrapper:
    _not_wrapped = ('_changeset', '_author', '_obj', '_commands', '_with_commands_executed', '_wrap_instances',
                    '_initial_values')
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

    def create_wrapped_model_class(self) -> typing.Type['ModelInstanceWrapper']:
        # noinspection PyTypeChecker
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
        updates = self._changeset.updated_existing.get(type(self._obj), {}).get(self._obj.pk, {})
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
                    value_pk = updates[field.name]
                    class_value = getattr(type(self._obj), field.name, None)
                    if isinstance(value_pk, str):
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

            self._changeset.add_update(self, name=field.name, value=new_value, author=author)

    def delete(self, author=None):
        if author is None:
            author = self._author
        self._changeset.add_delete(self, author=author)


def modifies_query(f):
    @wraps(f)
    def wrapper(self, *args, execute=False, **kwargs):
        if execute:
            return f(self, *args, **kwargs)
        if f.__name__ in ('filter', 'exclude'):
            kwargs = {name: (tuple(value) if name.endswith('__in') and isinstance(value, Iterable) else value)
                      for name, value in kwargs.items()}
        qs = self._wrap_queryset(self.get_queryset(), add_command=(f.__name__, args, kwargs))
        qs.execute_commands()
        return qs
    return wrapper


def executes_query(f):
    @wraps(f)
    def wrapper(self, *args, **kwargs):
        return f(self._with_commands_executed, *args, **kwargs)
    return wrapper


class BaseQueryWrapper(BaseWrapper):
    _allowed_callables = ('_add_hints', '_next_is_sticky', 'get_prefetch_queryset')

    def __init__(self, changeset, obj, author=None, commands=(), wrap_instances=True):
        super().__init__(changeset, obj, author)
        self._wrap_instances = wrap_instances
        self._commands = commands
        self._with_commands_executed = self

    def get_queryset(self):
        return self._obj

    def execute_commands(self):
        result = self
        for name, args, kwargs in self._commands:
            result = getattr(result, name)(*args, execute=True, **kwargs)
        result._commands = ()
        self._with_commands_executed = result

    def _wrap_instance(self, instance):
        if self._wrap_instances:
            return super()._wrap_instance(instance)
        return instance

    def _wrap_queryset(self, queryset, add_command=None, wrap_instances=None):
        if wrap_instances is None:
            wrap_instances = self._wrap_instances
        commands = self._commands
        if add_command is not None:
            commands += (add_command, )
        return QuerySetWrapper(self._changeset, queryset, self._author, commands, wrap_instances)

    @modifies_query
    def all(self):
        return self._wrap_queryset(self.get_queryset().all())

    @modifies_query
    def none(self):
        return self._wrap_queryset(self.get_queryset().none())

    @modifies_query
    def select_related(self, *args, **kwargs):
        return self._wrap_queryset(self.get_queryset().select_related(*args, **kwargs))

    @modifies_query
    def prefetch_related(self, *lookups):
        new_lookups = deque()
        for lookup in lookups:
            if not isinstance(lookup, str):
                new_lookups.append(lookup)
                continue
            model = self._obj.model
            for name in lookup.split('__'):
                model = model._meta.get_field(name).related_model
            qs = self._wrap_model(model).objects.all()
            qs._wrap_instances = False
            new_lookups.append(Prefetch(lookup, qs))
        return self._wrap_queryset(self.get_queryset().prefetch_related(*new_lookups))

    @executes_query
    def get(self, *args, **kwargs):
        results = tuple(self.filter(*args, **kwargs))
        if len(results) == 1:
            return self._wrap_instance(results[0])
        if results:
            raise self._obj.model.DoesNotExist
        raise self._obj.model.MultipleObjectsReturned

    @modifies_query
    def order_by(self, *args):
        return self._wrap_queryset(self.get_queryset().order_by(*args))

    def _filter_values(self, q, field_name, check):
        other_values = self._changeset.get_changed_values(self._obj.model, field_name)
        add_pks = []
        remove_pks = []
        for pk, new_value in other_values:
            (add_pks if check(new_value) else remove_pks).append(pk)
        return (q & ~Q(pk__in=remove_pks)) | Q(pk__in=add_pks)

    def _filter_kwarg(self, filter_name, filter_value):
        print(filter_name, '=', filter_value, sep='')

        segments = filter_name.split('__')
        field_name = segments.pop(0)
        try:
            class_value = getattr(self._obj.model, field_name)
        except AttributeError:
            raise ValueError('%s has no attribute %s' % (self._obj.model, field_name))

        q = Q(**{filter_name: filter_value})

        if field_name == 'pk' or field_name == self._obj.model._meta.pk.name:
            if not segments:
                return q
            else:
                return q

        if isinstance(class_value, ForwardManyToOneDescriptor):
            if not segments:
                filter_name = field_name + '__pk'
                filter_value = filter_value.pk
                segments = ['pk']
                q = Q(**{filter_name: filter_value})

            filter_type = segments.pop(0)

            if not segments and filter_type == 'in':
                filter_name = field_name+'__pk__in'
                filter_value = tuple(obj.pk for obj in filter_value)
                filter_type = 'pk'
                segments = ['in']
                q = Q(**{filter_name: filter_value})

            if filter_type == class_value.field.model._meta.pk.name:
                filter_type = 'pk'

            if filter_type == 'pk' and segments == ['in']:
                return self._filter_values(q, field_name, lambda val: val in filter_value)

            if segments:
                raise NotImplementedError

            if filter_type == 'pk':
                return self._filter_values(q, field_name, lambda val: val == filter_value)

            if filter_type == 'isnull':
                return self._filter_values(q, field_name, lambda val: (val is None) is filter_value)

            raise NotImplementedError

        if isinstance(class_value, ManyToManyDescriptor):
            if not segments:
                filter_name = field_name + '__pk'
                filter_value = filter_value.pk
                segments = ['pk']
                q = Q(**{filter_name: filter_value})

            filter_type = segments.pop(0)

            if filter_type == class_value.field.model._meta.pk.name:
                filter_type = 'pk'

            if segments:
                raise NotImplementedError

            if filter_type == 'pk':
                if class_value.reverse:
                    model = class_value.field.model
                    return ((q & ~Q(pk__in=self._changeset.m2m_remove_existing.get(model, {}).get(filter_value, ()))) |
                            Q(pk__in=self._changeset.m2m_add_existing.get(model, {}).get(filter_value, ())))

                raise NotImplementedError

            raise NotImplementedError

        if isinstance(class_value, DeferredAttribute):
            if not segments:
                raise NotImplementedError

            filter_type = segments.pop(0)

            if segments:
                raise NotImplementedError

            if filter_type == 'lt':
                return self._filter_values(q, field_name, lambda val: val < filter_value)

            raise NotImplementedError

        raise NotImplementedError('cannot filter %s by %s (%s)' % (self._obj.model, filter_name, class_value))

    def _filter_q(self, q):
        result = Q(*((self._filter_q(c) if isinstance(c, Q) else self._filter_kwarg(*c)) for c in q.children))
        result.connector = q.connector
        result.negated = q.negated
        return result

    def _filter(self, *args, **kwargs):
        return chain(
            tuple(self._filter_q(q) for q in args),
            tuple(self._filter_kwarg(name, value) for name, value in kwargs.items())
        )

    @modifies_query
    def filter(self, *args, **kwargs):
        return self._wrap_queryset(self.get_queryset().filter(*self._filter(*args, **kwargs)))

    @modifies_query
    def exclude(self, *args, **kwargs):
        return self._wrap_queryset(self.get_queryset().exclude(*self._filter(*args, **kwargs)))

    @executes_query
    def count(self):
        return self.get_queryset().count()

    @executes_query
    def values_list(self, *args, flat=False):
        return self.get_queryset().values_list(*args, flat=flat)

    @executes_query
    def first(self):
        first = self.get_queryset().first()
        if first is not None:
            first = self._wrap_instance(first)
        return first

    @modifies_query
    def using(self, alias):
        return self._wrap_queryset(self.get_queryset().using(alias))

    @executes_query
    def __iter__(self):
        return iter((self._wrap_instance(instance) for instance in self.get_queryset()))

    @executes_query
    def iterator(self):
        return iter((self._wrap_instance(instance) for instance in self.get_queryset().iterator()))

    @executes_query
    def __len__(self):
        return len(self.get_queryset())


class ManagerWrapper(BaseQueryWrapper):
    def get_queryset(self):
        return self._obj.exclude(pk__in=self._changeset.deleted_existing.get(self._obj.model, ()))


class RelatedManagerWrapper(ManagerWrapper):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _get_cache_name(self):
        return self._obj.field.related_query_name()

    def get_queryset(self):
        return self.model.objects.filter(**self._obj.core_filters)

    def all(self):
        try:
            return self.instance._prefetched_objects_cache[self._get_cache_name()]
        except(AttributeError, KeyError):
            pass
        return self.get_queryset().all()


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

    def all(self):
        return self.model.objects.filter(**self._obj.core_filters)


class QuerySetWrapper(BaseQueryWrapper):
    @property
    def _iterable_class(self):
        return self._obj._iterable_class
