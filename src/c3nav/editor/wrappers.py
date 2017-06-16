import operator
import typing
from collections import deque
from functools import reduce
from itertools import chain

from django.db import models
from django.db.models import Manager, Prefetch, Q
from django.db.models.fields.related_descriptors import ForwardManyToOneDescriptor, ManyToManyDescriptor
from django.db.models.query_utils import DeferredAttribute
from django.utils.functional import cached_property


class BaseWrapper:
    _not_wrapped = ('_changeset', '_author', '_obj', '_created_pks', '_result', '_initial_values', '_wrap_instances')
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
                raise TypeError('Can not call %s.%s wrapped!' % (type(self), name))
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

            self._changeset.add_update(self, name=field.name, value=field.get_prep_value(new_value), author=author)

    def delete(self, author=None):
        if author is None:
            author = self._author
        self._changeset.add_delete(self, author=author)


class BaseQueryWrapper(BaseWrapper):
    _allowed_callables = ('_add_hints', '_next_is_sticky', 'get_prefetch_queryset')

    def __init__(self, changeset, obj, author=None, created_pks=None, wrap_instances=True):
        super().__init__(changeset, obj, author)
        if created_pks is None:
            created_pks = self._changeset.get_created_pks(self._obj.model)
        self._created_pks = created_pks
        self._wrap_instances = wrap_instances
        self._result = None

    def get_queryset(self):
        return self._obj

    def _wrap_instance(self, instance):
        if self._wrap_instances:
            return super()._wrap_instance(instance)
        return instance

    def _wrap_queryset(self, queryset, created_pks=None, wrap_instances=None):
        if created_pks is None:
            created_pks = self._created_pks
        if wrap_instances is None:
            wrap_instances = self._wrap_instances
        return QuerySetWrapper(self._changeset, queryset, self._author, created_pks, wrap_instances)

    def all(self):
        return self._wrap_queryset(self.get_queryset().all())

    def none(self):
        return self._wrap_queryset(self.get_queryset().none(), created_pks=set())

    def select_related(self, *args, **kwargs):
        return self._wrap_queryset(self.get_queryset().select_related(*args, **kwargs))

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

    def get(self, *args, **kwargs):
        results = tuple(self.filter(*args, **kwargs))
        if len(results) == 1:
            return self._wrap_instance(results[0])
        if results:
            raise self._obj.model.MultipleObjectsReturned
        raise self._obj.model.DoesNotExist

    def order_by(self, *args):
        return self._wrap_queryset(self.get_queryset().order_by(*args))

    def _filter_values(self, q, field_name, check):
        other_values = self._changeset.get_changed_values(self._obj.model, field_name)
        add_pks = []
        remove_pks = []
        for pk, new_value in other_values:
            (add_pks if check(new_value) else remove_pks).append(pk)
        created_pks = set()
        for pk, values in self._changeset.created_objects.get(self._obj.model, {}).items():
            try:
                if check(values[field_name]):
                    created_pks.add(pk)
                continue
            except AttributeError:
                pass
            if check(getattr(self._changeset.get_created_object(self._obj.model, pk), field_name)):
                created_pks.add(pk)
        return (q & ~Q(pk__in=remove_pks)) | Q(pk__in=add_pks), created_pks

    @staticmethod
    def is_created_pk(pk):
        return isinstance(pk, str) and pk.startswith('c') and pk[1:].isnumeric()

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
                if self.is_created_pk(filter_value):
                    return Q(pk__in=()), set([int(filter_value[1:])])
                return q, set()
            elif segments == ['in']:
                return (Q(pk__in=tuple(pk for pk in filter_value if not self.is_created_pk(pk))),
                        set(int(pk[1:]) for pk in filter_value if self.is_created_pk(pk)))

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
                q = Q(**{field_name+'__pk__in': tuple(pk for pk in filter_value if not self.is_created_pk(pk))})
                filter_value = tuple(str(pk) for pk in filter_value)
                return self._filter_values(q, field_name, lambda val: str(val) in filter_value)

            if segments:
                raise NotImplementedError

            if filter_type == 'pk':
                if self.is_created_pk(filter_value):
                    q = Q(pk__in=())
                filter_value = str(filter_value)
                return self._filter_values(q, field_name, lambda val: str(val) == filter_value)

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
                    # todo: implement this for created models
                    model = class_value.field.model

                    if self.is_created_pk(filter_value):
                        filter_value = int(filter_value[1:])
                        pks = tuple(self._changeset.created_objects[model][filter_value].get(field_name, ()))
                        return (Q(pk__in=(pk for pk in pks if not self.is_created_pk(pk))),
                                set(int(pk[1:]) for pk in pks if self.is_created_pk(pk)))

                    def get_changeset_m2m(items):
                        return items.get(model, {}).get(filter_value, {}).get(field_name, ())

                    remove_pks = get_changeset_m2m(self._changeset.m2m_remove_existing)
                    add_pks = get_changeset_m2m(self._changeset.m2m_add_existing)
                    return (((q & ~Q(pk__in=(pk for pk in remove_pks if not self.is_created_pk(pk)))) |
                             Q(pk__in=(pk for pk in remove_pks if not self.is_created_pk(pk)))),
                            set(int(pk[1:]) for pk in add_pks if self.is_created_pk(pk)))

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
        filters, created_pks = zip(*((self._filter_q(c) if isinstance(c, Q) else self._filter_kwarg(*c))
                                     for c in q.children))
        result = Q(*filters)
        result.connector = q.connector
        result.negated = q.negated

        created_pks = reduce(operator.and_ if q.connector == 'AND' else operator.or_, created_pks)
        if q.negated:
            created_pks = self._changeset.get_created_pks(self._obj.model)-created_pks
        return result, created_pks

    def _filter_or_exclude(self, negate, *args, **kwargs):
        filters, created_pks = zip(*tuple(chain(
            tuple(self._filter_q(q) for q in args),
            tuple(self._filter_kwarg(name, value) for name, value in kwargs.items())
        )))

        created_pks = reduce(operator.and_, created_pks)
        if negate:
            created_pks = self._changeset.get_created_pks(self._obj.model) - created_pks
        return self._wrap_queryset(self.get_queryset().filter(*filters), created_pks=(self._created_pks & created_pks))

    def filter(self, *args, **kwargs):
        return self._filter_or_exclude(False, *args, **kwargs)

    def exclude(self, *args, **kwargs):
        return self._filter_or_exclude(True, *args, **kwargs)

    def count(self):
        return self.get_queryset().count()+len(tuple(self._get_created_objects()))

    def values_list(self, *args, flat=False):
        return self.get_queryset().values_list(*args, flat=flat)

    def first(self):
        first = self.get_queryset().first()
        if first is not None:
            first = self._wrap_instance(first)
        return first

    def using(self, alias):
        return self._wrap_queryset(self.get_queryset().using(alias))

    def _get_created_objects(self):
        if not self._wrap_instances:
            return ()
        return (self._changeset.get_created_object(self._obj.model, pk, get_foreign_objects=True)
                for pk in sorted(self._created_pks))

    @cached_property
    def _cached_result(self):
        return (tuple(self._wrap_instance(instance) for instance in self.get_queryset()) +
                tuple(self._get_created_objects()))

    def __iter__(self):
        return iter(self._cached_result)

    def iterator(self):
        return iter(chain(
            (self._wrap_instance(instance) for instance in self.get_queryset().iterator()),
            self._get_created_objects(),
        ))

    def __len__(self):
        return len(self._cached_result)

    def create(self, *args, **kwargs):
        obj = self.model(*args, **kwargs)
        obj.save()
        return obj


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

    def create(self, *args, **kwargs):
        kwargs[self._obj.field.name] = self.instance
        super().create(*args, **kwargs)


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

    def create(self, *args, **kwargs):
        raise NotImplementedError


class QuerySetWrapper(BaseQueryWrapper):
    @property
    def _iterable_class(self):
        return self._obj._iterable_class
