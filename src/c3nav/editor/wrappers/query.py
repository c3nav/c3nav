import operator
from collections import OrderedDict
from functools import reduce, wraps
from itertools import chain

from django.db.models import DeferredAttribute, ManyToManyRel, Prefetch, Q
from django.db.models.fields.related_descriptors import ForwardManyToOneDescriptor, ManyToManyDescriptor
from django.utils.functional import cached_property

from c3nav.editor.utils import is_created_pk
from c3nav.editor.wrappers.base import BaseWrapper


def get_queryset(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        if hasattr(self, 'get_queryset'):
            return getattr(self.get_queryset(), func.__name__)(*args, **kwargs)
        return func(self, *args, **kwargs)
    return wrapper


def queryset_only(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        if hasattr(self, 'get_queryset'):
            raise TypeError
        return func(self, *args, **kwargs)
    return wrapper


class BaseQueryWrapper(BaseWrapper):
    _allowed_callables = ('_add_hints', 'get_prefetch_queryset', '_apply_rel_filters')

    def __init__(self, changeset, obj, author=None, created_pks=None, extra=()):
        super().__init__(changeset, obj, author)
        if created_pks is None:
            created_pks = self._get_initial_created_pks()
        self._created_pks = created_pks
        self._extra = extra

    def _get_initial_created_pks(self):
        self.model.get_submodels(self.model._obj)
        return reduce(operator.or_, (self._changeset.get_created_pks(model) for model in self.model._submodels))

    def _wrap_instance(self, instance):
        return super()._wrap_instance(instance)

    def _wrap_queryset(self, queryset, created_pks=None, add_extra=()):
        if created_pks is None:
            created_pks = self._created_pks
        if created_pks is False:
            created_pks = None
        return QuerySetWrapper(self._changeset, queryset, self._author, created_pks, self._extra+add_extra)

    @get_queryset
    def all(self):
        return self._wrap_queryset(self._obj.all())

    @get_queryset
    def none(self):
        return self._wrap_queryset(self._obj.none(), ())

    @get_queryset
    def select_related(self, *args, **kwargs):
        return self._wrap_queryset(self._obj.select_related(*args, **kwargs))

    @get_queryset
    def prefetch_related(self, *lookups):
        lookups_splitted = tuple(tuple(lookup.split('__')) for lookup in lookups)
        max_depth = max(len(lookup) for lookup in lookups_splitted)
        lookups_by_depth = []
        for i in range(max_depth):
            lookups_by_depth.append(set(tuple(lookup[:i+1] for lookup in lookups_splitted if len(lookup) > i)))

        lookup_models = {(): self._obj.model}
        lookup_querysets = {(): self._obj}
        for depth_lookups in lookups_by_depth:
            for lookup in depth_lookups:
                model = lookup_models[lookup[:-1]]._meta.get_field(lookup[-1]).related_model
                lookup_models[lookup] = model
                lookup_querysets[lookup] = self._wrap_model(model).objects.all()._obj

        for depth_lookups in reversed(lookups_by_depth):
            for lookup in depth_lookups:
                qs = self._wrap_queryset(lookup_querysets[lookup], created_pks=False)
                prefetch = Prefetch(lookup[-1], qs)
                lookup_querysets[lookup[:-1]] = lookup_querysets[lookup[:-1]].prefetch_related(prefetch)

        return self._wrap_queryset(lookup_querysets[()])

    def _clone(self, **kwargs):
        clone = self._wrap_queryset(self._obj)
        clone._obj.__dict__.update(kwargs)
        return clone

    @get_queryset
    def get(self, *args, **kwargs):
        results = tuple(self.filter(*args, **kwargs))
        if len(results) == 1:
            return self._wrap_instance(results[0])
        if results:
            raise self._obj.model.MultipleObjectsReturned
        raise self._obj.model.DoesNotExist

    @get_queryset
    def exists(self, *args, **kwargs):
        if self._created_pks:
            return True
        return self._obj.exists()

    @get_queryset
    def order_by(self, *args):
        return self._wrap_queryset(self._obj.order_by(*args))

    def _filter_values(self, q, field_name, check):
        other_values = ()
        submodels = [model for model in self.model._submodels]
        for model in submodels:
            other_values += self._changeset.get_changed_values(model, field_name)
        add_pks = []
        remove_pks = []
        for pk, new_value in other_values:
            (add_pks if check(new_value) else remove_pks).append(pk)
        created_pks = set()
        for pk, values in chain(*(self._changeset.created_objects.get(model, {}).items() for model in submodels)):
            field_name = getattr(model._meta.get_field(field_name), 'attname', field_name)
            if check(getattr(self._changeset.get_created_object(self._obj.model, pk), field_name)):
                created_pks.add(pk)

        return (q & ~Q(pk__in=remove_pks)) | Q(pk__in=add_pks), created_pks

    def _filter_kwarg(self, filter_name, filter_value):
        # print(filter_name, '=', filter_value, sep='')

        segments = filter_name.split('__')
        field_name = segments.pop(0)
        try:
            class_value = getattr(self._obj.model, field_name)
        except AttributeError:
            raise ValueError('%s has no attribute %s' % (self._obj.model, field_name))

        q = Q(**{filter_name: filter_value})

        if field_name == 'pk' or field_name == self._obj.model._meta.pk.name:
            if not segments:
                if is_created_pk(filter_value):
                    return Q(pk__in=()), set([int(filter_value[1:])])
                return q, set()
            elif segments == ['in']:
                return (Q(pk__in=tuple(pk for pk in filter_value if not is_created_pk(pk))),
                        set(int(pk[1:]) for pk in filter_value if is_created_pk(pk)))

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
                q = Q(**{field_name+'__pk__in': tuple(pk for pk in filter_value if not is_created_pk(pk))})
                filter_value = tuple(str(pk) for pk in filter_value)
                return self._filter_values(q, field_name, lambda val: str(val) in filter_value)

            if segments:
                raise NotImplementedError

            if filter_type == 'pk':
                if is_created_pk(filter_value):
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

            if not segments and filter_type == 'in':
                filter_name = field_name+'__pk__in'
                filter_value = tuple(obj.pk for obj in filter_value)
                filter_type = 'pk'
                segments = ['in']
                q = Q(**{filter_name: filter_value})

            if filter_type == class_value.field.model._meta.pk.name:
                filter_type = 'pk'

            if filter_type == 'pk' and segments == ['in']:
                if not class_value.reverse:
                    raise NotImplementedError

                # so... e.g. we want to get all groups that belong to one of the given spaces.
                # field_name would be "spaces"
                model = class_value.field.model  # space
                filter_value = set(filter_value)  # space pks
                filter_value_existing = set(pk for pk in filter_value if not is_created_pk(pk))
                rel_name = class_value.field.name

                # get spaces that we are interested about that had groups added or removed
                m2m_added = {pk: val[rel_name] for pk, val in self._changeset.m2m_added.get(model, {}).items()
                             if pk in filter_value and rel_name in val}
                m2m_removed = {pk: val[rel_name] for pk, val in self._changeset.m2m_removed.get(model, {}).items()
                               if pk in filter_value and rel_name in val}  # can only be existing spaces

                # directly lookup groups for spaces that had no groups removed
                q = Q(**{field_name+'__pk__in': filter_value_existing - set(m2m_removed.keys())})

                # lookup groups for spaces that had groups removed
                for pk, values in m2m_removed.items():
                    q |= Q(Q(**{field_name+'__pk': pk}) & ~Q(pk__in=values))

                # get pk of groups that were added to any of the spaces
                r_added_pks = reduce(operator.or_, m2m_added.values(), set())

                # lookup existing groups that were added to any of the spaces
                q |= Q(pk__in=tuple(pk for pk in r_added_pks if not is_created_pk(pk)))

                # get created groups that were added to any of the spaces
                created_pks = set(int(pk[1:]) for pk in r_added_pks if is_created_pk(pk))

                return q, created_pks

            if segments:
                raise NotImplementedError

            if filter_type == 'pk':
                if class_value.reverse:
                    model = class_value.field.model

                    def get_changeset_m2m(items):
                        return items.get(model, {}).get(filter_value, {}).get(class_value.field.name, ())

                    remove_pks = get_changeset_m2m(self._changeset.m2m_removed)
                    add_pks = get_changeset_m2m(self._changeset.m2m_added)

                    if is_created_pk(filter_value):
                        pks = add_pks
                        return (Q(pk__in=(pk for pk in pks if not is_created_pk(pk))),
                                set(int(pk[1:]) for pk in pks if is_created_pk(pk)))

                    return (((q & ~Q(pk__in=(pk for pk in remove_pks if not is_created_pk(pk)))) |
                             Q(pk__in=(pk for pk in add_pks if not is_created_pk(pk)))),
                            set(int(pk[1:]) for pk in add_pks if is_created_pk(pk)))

                raise NotImplementedError

            raise NotImplementedError

        if isinstance(class_value, DeferredAttribute):
            if not segments:
                return self._filter_values(q, field_name, lambda val: val == filter_value)

            filter_type = segments.pop(0)

            if segments:
                raise NotImplementedError

            if filter_type == 'in':
                return self._filter_values(q, field_name, lambda val: val in filter_value)

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
            created_pks = self._get_initial_created_pks()-created_pks
        return result, created_pks

    def _filter_or_exclude(self, negate, *args, **kwargs):
        filters, created_pks = zip(*tuple(chain(
            tuple(self._filter_q(q) for q in args),
            tuple(self._filter_kwarg(name, value) for name, value in kwargs.items())
        )))

        created_pks = reduce(operator.and_, created_pks)
        if negate:
            filters = (~Q(*filters), )
            created_pks = self._get_initial_created_pks()-created_pks
        return self._wrap_queryset(self._obj.filter(*filters), created_pks=(self._created_pks & created_pks))

    @get_queryset
    def filter(self, *args, **kwargs):
        return self._filter_or_exclude(False, *args, **kwargs)

    @get_queryset
    def exclude(self, *args, **kwargs):
        return self._filter_or_exclude(True, *args, **kwargs)

    @get_queryset
    def count(self):
        return self._obj.count()+len(tuple(self._get_created_objects(get_foreign_objects=False)))

    @get_queryset
    def values_list(self, *args, flat=False):
        own_values = (tuple(getattr(obj, arg) for arg in args) for obj in self._get_created_objects())
        if flat:
            own_values = (v[0] for v in own_values)
        return tuple(chain(
            self._obj.values_list(*args, flat=flat),
            own_values,
        ))

    @get_queryset
    def first(self):
        first = self._obj.first()
        if first is not None:
            first = self._wrap_instance(first)
        return first

    @get_queryset
    def using(self, alias):
        return self._wrap_queryset(self._obj.using(alias))

    @get_queryset
    def extra(self, select):
        for key in select.keys():
            if not key.startswith('_prefetch_related_val'):
                raise NotImplementedError('extra() calls are only supported for prefetch_related!')
        return self._wrap_queryset(self._obj.extra(select), add_extra=tuple(select.keys()))

    @get_queryset
    def _next_is_sticky(self):
        return self._wrap_queryset(self._obj._next_is_sticky())

    def _get_created_objects(self, get_foreign_objects=True):
        return (self._changeset.get_created_object(self._obj.model, pk, get_foreign_objects=get_foreign_objects)
                for pk in sorted(self._created_pks))

    @queryset_only
    def _get_cached_result(self):
        obj = self._obj
        obj._prefetch_done = True
        obj._fetch_all()

        result = [self._wrap_instance(instance) for instance in obj._result_cache]
        obj._result_cache = result
        obj._prefetch_done = False
        obj._fetch_all()

        result += list(self._get_created_objects())

        for extra in self._extra:
            ex = extra[22:]
            for f in self._obj.model._meta.get_fields():
                if isinstance(f, ManyToManyRel) and f.through._meta.get_field(f.field.m2m_field_name()).attname == ex:
                    objs_by_pk = OrderedDict()
                    for instance in result:
                        objs_by_pk.setdefault(instance.pk, OrderedDict())[getattr(instance, extra, None)] = instance

                    m2m_added = self._changeset.m2m_added.get(f.field.model, {})
                    m2m_removed = self._changeset.m2m_removed.get(f.field.model, {})
                    for related_pk, changes in m2m_added.items():
                        for pk in changes.get(f.field.name, ()):
                            if pk in objs_by_pk and related_pk not in objs_by_pk[pk]:
                                new = self._wrap_instance(next(iter(objs_by_pk[pk].values()))._obj)
                                new.__dict__[extra] = related_pk
                                objs_by_pk[pk][related_pk] = new

                    for related_pk, changes in m2m_removed.items():
                        for pk in changes.get(f.field.name, ()):
                            if pk in objs_by_pk and related_pk in objs_by_pk[pk]:
                                objs_by_pk[pk].pop(related_pk)

                    for pk, instances in objs_by_pk.items():
                        instances.pop(None, None)

                    result = list(chain(*(instances.values() for instances in objs_by_pk.values())))
                    break
            else:
                raise NotImplementedError('Cannot do extra() for '+extra)

        obj._result_cache = result
        return result

    @cached_property
    def _cached_result(self):
        return self._get_cached_result()

    @property
    def _result_cache(self):
        return self._cached_result

    @_result_cache.setter
    def _result_cache(self, value):
        self.__dict__['_cached_result'] = value

    @queryset_only
    def __iter__(self):
        return iter(self._cached_result)

    @queryset_only
    def iterator(self):
        return iter(chain(
            (self._wrap_instance(instance) for instance in self._obj.iterator()),
            self._get_created_objects(),
        ))

    @queryset_only
    def __len__(self):
        return len(self._cached_result)

    def create(self, *args, **kwargs):
        obj = self.model(*args, **kwargs)
        obj.save()
        return obj

    @get_queryset
    def delete(self):
        for obj in self:
            obj.delete()


class QuerySetWrapper(BaseQueryWrapper):
    @property
    def _iterable_class(self):
        return self._obj._iterable_class
