import operator
import typing
from collections import OrderedDict
from functools import reduce, wraps
from itertools import chain

from django.db import models
from django.db.models import Field, Manager, ManyToManyRel, Prefetch, Q
from django.db.models.fields.related_descriptors import ForwardManyToOneDescriptor, ManyToManyDescriptor
from django.db.models.query_utils import DeferredAttribute
from django.utils.functional import cached_property

from c3nav.editor.forms import create_editor_form
from c3nav.editor.utils import is_created_pk


class BaseWrapper:
    """
    Base Class for all wrappers.
    Saves wrapped object along with the changeset and the author for new changes.
    getattr, setattr and delattr will be forwarded to the object, exceptions are specified in _not_wrapped.
    If the value of an attribute is a model, model instance, manager or queryset, it will be wrapped, to.
    Callables will only be returned be getattr when they are inside _allowed_callables.
    Callables in _wrapped_callables will be returned wrapped, so that their self if the wrapping instance.
    """
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
        """
        Wrap a model, with same changeset and author as this wrapper.
        """
        if isinstance(model, type) and issubclass(model, ModelInstanceWrapper):
            model = model._parent
        if isinstance(model, ModelWrapper):
            if self._author == model._author and self._changeset == model._changeset:
                return model
            model = model._obj
        assert issubclass(model, models.Model)
        return ModelWrapper(self._changeset, model, self._author)

    def _wrap_instance(self, instance):
        """
        Wrap a model instance, with same changeset and author as this wrapper.
        """
        if isinstance(instance, ModelInstanceWrapper):
            if self._author == instance._author and self._changeset == instance._changeset:
                return instance
            instance = instance._obj
        assert isinstance(instance, models.Model)
        return self._wrap_model(type(instance)).create_wrapped_model_class()(self._changeset, instance, self._author)

    def _wrap_manager(self, manager):
        """
        Wrap a manager, with same changeset and author as this wrapper.
        Detects RelatedManager or ManyRelatedmanager instances and chooses the Wrapper accordingly.
        """
        assert isinstance(manager, Manager)
        if hasattr(manager, 'through'):
            return ManyRelatedManagerWrapper(self._changeset, manager, self._author)
        if hasattr(manager, 'instance'):
            return RelatedManagerWrapper(self._changeset, manager, self._author)
        return ManagerWrapper(self._changeset, manager, self._author)

    def _wrap_queryset(self, queryset):
        """
        Wrap a queryset, with same changeset and author as this wrapper.
        """
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


class ModelWrapper(BaseWrapper):
    """
    Wraps a model class.
    Can be compared to other wrapped or non-wrapped model classes.
    Can be called (like a class) to get a wrapped model instance
    that has the according ModelWrapper as its type / metaclass.
    """
    _submodels_by_model = {}

    def __eq__(self, other):
        if type(other) == ModelWrapper:
            return self._obj is other._obj
        return self._obj is other

    # noinspection PyPep8Naming
    @cached_property
    def EditorForm(self):
        """
        Returns an editor form for this model.
        """
        return create_editor_form(self._obj)

    @classmethod
    def get_submodels(cls, model: models.Model) -> typing.List[typing.Type[models.Model]]:
        """
        Get non-abstract submodels for a model including the model itself.
        Result is cached.
        """
        try:
            return cls._submodels_by_model[model]
        except KeyError:
            pass
        all_models = model.__subclasses__()
        result = []
        if not model._meta.abstract:
            result.append(model)
        result.extend(chain(*(cls.get_submodels(model) for model in all_models)))
        cls._submodels_by_model[model] = result
        return result

    @cached_property
    def _submodels(self):
        """
        Get non-abstract submodels for this model including the model itself.
        """
        return self.get_submodels(self._obj)

    def create_wrapped_model_class(self) -> typing.Type['ModelInstanceWrapper']:
        """
        Return a ModelInstanceWrapper that has a proxy to this instance as its type / metaclass. #voodoo
        """
        # noinspection PyTypeChecker
        return self.create_metaclass()(self._obj.__name__ + 'InstanceWrapper', (ModelInstanceWrapper,), {})

    def __call__(self, **kwargs):
        """
        Create a wrapped instance of this model. _wrap_instance will call create_wrapped_model_class().
        """
        instance = self._wrap_instance(self._obj())
        for name, value in kwargs.items():
            setattr(instance, name, value)
        return instance

    def create_metaclass(self):
        """
        Create the proxy metaclass for craeate_wrapped_model_class().
        """
        parent = self

        class ModelInstanceWrapperMeta(type):
            _parent = parent

            def __getattr__(self, name):
                return getattr(parent, name)

            def __setattr__(self, name, value):
                setattr(parent, name, value)

            def __delattr__(self, name):
                delattr(parent, name)

        ModelInstanceWrapperMeta.__name__ = self._obj.__name__+'InstanceWrapperMeta'

        return ModelInstanceWrapperMeta

    def __repr__(self):
        return '<ModelWrapper '+repr(self._obj.__name__)+'>'


class ModelInstanceWrapper(BaseWrapper):
    """
    Wraps a model instance. Don't use this directly, call a ModelWrapper instead / use ChangeSet.wrap().
    Creates changes in changeset when save() is called.
    Updates updated values on existing objects on init.
    Can be compared to other wrapped or non-wrapped model instances.
    """
    _allowed_callables = ('full_clean', '_perform_unique_checks', '_perform_date_checks')
    _wrapped_callables = ('validate_unique', '_get_pk_val')

    def __init__(self, *args, **kwargs):
        """
        Get initial values of this instance, so we know what changed on save.
        Updates values according to cangeset if this is an existing object.
        """
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
        """
        We have to intercept here because RelatedFields won't accept
        Wrapped model instances values, so we have to trick them.
        """
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
        """
        Create changes in changeset instead of saving.
        """
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


def get_queryset(func):
    """
    Wraps methods of BaseQueryWrapper that manipulate a queryset.
    If self is a Manager, not an object, preceed the method call with a filter call according to the manager.
    """
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        if hasattr(self, 'get_queryset'):
            return getattr(self.get_queryset(), func.__name__)(*args, **kwargs)
        return func(self, *args, **kwargs)
    return wrapper


class BaseQueryWrapper(BaseWrapper):
    """
    Base class for everything that wraps a QuerySet or manager.
    Don't use this directly, but via WrappedModel.objects or WrappedInstance.groups or similar.
    Intercepts all query methods to exclude ids / include ids for each filter according to changeset changes.
    Keeps track of which created objects the current filtering still applies to.
    When evaluated, just does everything as if the queryset was applied to the databse.
    """
    _allowed_callables = ('_add_hints', 'get_prefetch_queryset', '_apply_rel_filters')

    def __init__(self, changeset, obj, author=None, created_pks=None, extra=()):
        super().__init__(changeset, obj, author)
        if created_pks is None:
            created_pks = self._get_initial_created_pks()
        self._created_pks = created_pks
        self._extra = extra

    def _get_initial_created_pks(self):
        """
        Get all created pks for this query's model an submodels.
        """
        self.model.get_submodels(self.model._obj)
        return reduce(operator.or_, (self._changeset.get_created_pks(model) for model in self.model._submodels))

    def _wrap_queryset(self, queryset, created_pks=None, add_extra=()):
        """
        Wraps a queryset, usually after manipulating the current one.
        :param created_pks: set of created pks to be still in the next queryset (the same ones as this one by default)
        :param add_extra: extra() calls that have been added to the query
        """
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
        """
        We split up all prefetch related lookups into one-level prefetches
        and convert them into Prefetch() objects with custom querysets.
        This makes sure that the prefetch also happens on the virtually modified database.
        """
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
        """
        Order by is not yet supported on created instances because this is not needed so far.
        """
        return self._wrap_queryset(self._obj.order_by(*args))

    def _filter_values(self, q, field_name, check):
        """
        Filter by value.
        :param q: base Q object to give to the database and to modify
        :param field_name: name of the field whose value should be compared
        :param check: comparision function that only gets the new value
        :return: new Q object and set of matched existing pks
        """
        other_values = ()
        submodels = [model for model in self.model._submodels]
        for model in submodels:
            other_values += self._changeset.get_changed_values(model, field_name)
        add_pks = []
        remove_pks = []
        for pk, new_value in other_values:
            (add_pks if check(new_value) else remove_pks).append(pk)
        created_pks = set()
        for model in submodels:
            for pk, values in self._changeset.created_objects.get(model, {}).items():
                field_name = getattr(model._meta.get_field(field_name), 'attname', field_name)
                if check(getattr(self._changeset.get_created_object(self._obj.model, pk), field_name)):
                    created_pks.add(pk)

        return (q & ~Q(pk__in=remove_pks)) | Q(pk__in=add_pks), created_pks

    def _filter_kwarg(self, filter_name, filter_value):
        """
        filter by kwarg.
        The core filtering happens here, as also Q objects are just a collection / combination of kwarg filters.
        :return: new Q object and set of matched existing pks
        """
        # print(filter_name, '=', filter_value, sep='')

        segments = filter_name.split('__')
        field_name = segments.pop(0)
        try:
            class_value = getattr(self._obj.model, field_name)
        except AttributeError:
            raise ValueError('%s has no attribute %s' % (self._obj.model, field_name))

        # create a base q that we'll modify later
        q = Q(**{filter_name: filter_value})

        # check if the filter begins with pk or the name of the primary key
        if field_name == 'pk' or field_name == self._obj.model._meta.pk.name:
            if not segments:
                # if the check is just 'pk' or the name or the name of the primary key, return the mathing object
                if is_created_pk(filter_value):
                    return Q(pk__in=()), set([int(filter_value[1:])])
                return q, set()
            elif segments == ['in']:
                # if the check is 'pk__in' it's nearly as easy
                return (Q(pk__in=tuple(pk for pk in filter_value if not is_created_pk(pk))),
                        set(int(pk[1:]) for pk in filter_value if is_created_pk(pk)))

        # check if we are filtering by a foreign key field
        if isinstance(class_value, ForwardManyToOneDescriptor):
            if not segments:
                # turn 'foreign_obj' into 'foreign_obj__pk' for later
                filter_name = field_name + '__pk'
                filter_value = filter_value.pk
                segments = ['pk']
                q = Q(**{filter_name: filter_value})

            filter_type = segments.pop(0)

            if not segments and filter_type == 'in':
                # turn 'foreign_obj__in' into 'foreign_obj__pk' for later
                filter_name = field_name+'__pk__in'
                filter_value = tuple(obj.pk for obj in filter_value)
                filter_type = 'pk'
                segments = ['in']
                q = Q(**{filter_name: filter_value})

            if filter_type == class_value.field.model._meta.pk.name:
                # turn <name of the primary key field> into pk for later
                filter_type = 'pk'

            if filter_type == 'pk' and segments == ['in']:
                # foreign_obj__pk__in
                q = Q(**{field_name+'__pk__in': tuple(pk for pk in filter_value if not is_created_pk(pk))})
                filter_value = tuple(str(pk) for pk in filter_value)
                return self._filter_values(q, field_name, lambda val: str(val) in filter_value)

            if segments:
                # wo don't do multi-level lookups
                raise NotImplementedError

            if filter_type == 'pk':
                # foreign_obj__pk
                if is_created_pk(filter_value):
                    q = Q(pk__in=())
                filter_value = str(filter_value)
                return self._filter_values(q, field_name, lambda val: str(val) == filter_value)

            if filter_type == 'isnull':
                # foreign_obj__isnull
                return self._filter_values(q, field_name, lambda val: (val is None) is filter_value)

            raise NotImplementedError

        # check if we are filtering by a many to many field
        if isinstance(class_value, ManyToManyDescriptor):
            if not segments:
                # turn 'm2m' into 'm2m__pk' for later
                filter_name = field_name + '__pk'
                filter_value = filter_value.pk
                segments = ['pk']
                q = Q(**{filter_name: filter_value})

            filter_type = segments.pop(0)

            if not segments and filter_type == 'in':
                # turn 'm2m__in' into 'm2m__pk__in' for later
                filter_name = field_name+'__pk__in'
                filter_value = tuple(obj.pk for obj in filter_value)
                filter_type = 'pk'
                segments = ['in']
                q = Q(**{filter_name: filter_value})

            if filter_type == class_value.field.model._meta.pk.name:
                # turn <name of the primary key field> into pk for later
                filter_type = 'pk'

            if filter_type == 'pk' and segments == ['in']:
                # m2m__pk__in
                if not class_value.reverse:
                    # we don't do this in reverse
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
                # we don't to multi-level lookups
                raise NotImplementedError

            if filter_type == 'pk':
                # m2m__pk
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

                # sorry, no reverse lookup
                raise NotImplementedError

            raise NotImplementedError

        # check if field is a deffered attribute, e.g. a CharField
        if isinstance(class_value, DeferredAttribute):
            if not segments:
                # field=
                return self._filter_values(q, field_name, lambda val: val == filter_value)

            filter_type = segments.pop(0)

            if segments:
                # we don't to field__whatever__whatever
                raise NotImplementedError

            if filter_type == 'in':
                # field__in
                return self._filter_values(q, field_name, lambda val: val in filter_value)

            if filter_type == 'lt':
                # field__lt
                return self._filter_values(q, field_name, lambda val: val < filter_value)

            raise NotImplementedError

        raise NotImplementedError('cannot filter %s by %s (%s)' % (self._obj.model, filter_name, class_value))

    def _filter_q(self, q):
        """
        filter by Q object.
        Split it up into recursive _filter_q and _filter_kwarg calls and combine them again.
        :return: new Q object and set of matched existing pks
        """
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
        """
        We only support the kind of extra() call that a many to many prefetch_related does.
        """
        for key in select.keys():
            if not key.startswith('_prefetch_related_val'):
                raise NotImplementedError('extra() calls are only supported for prefetch_related!')
        return self._wrap_queryset(self._obj.extra(select), add_extra=tuple(select.keys()))

    @get_queryset
    def _next_is_sticky(self):
        """
        Needed by prefetch_related.
        """
        return self._wrap_queryset(self._obj._next_is_sticky())

    def create(self, *args, **kwargs):
        obj = self.model(*args, **kwargs)
        obj.save()
        return obj


class ManagerWrapper(BaseQueryWrapper):
    """
    Wraps a manager.
    This class itself is used to wrap Model.objects managers.
    """
    def get_queryset(self):
        """
        make sure that the database does not return objects that have been deleted in this changeset
        """
        qs = self._wrap_queryset(self._obj.model.objects.all())
        return qs.exclude(pk__in=self._changeset.deleted_existing.get(self._obj.model, ()))

    def delete(self):
        self.get_queryset().delete()


class RelatedManagerWrapper(ManagerWrapper):
    """
    Wraps a related manager.
    """
    def _get_cache_name(self):
        """
        get cache name to fetch prefetch_related results
        """
        return self._obj.field.related_query_name()

    def get_queryset(self):
        """
        filter queryset by related manager filters
        """
        return super().get_queryset().filter(**self._obj.core_filters)

    def all(self):
        """
        get prefetched result if it exists
        """
        try:
            return self.instance._prefetched_objects_cache[self._get_cache_name()]
        except(AttributeError, KeyError):
            pass
        return super().all()

    def create(self, *args, **kwargs):
        if self.instance.pk is None:
            raise TypeError
        kwargs[self._obj.field.name] = self.instance
        super().create(*args, **kwargs)


class ManyRelatedManagerWrapper(RelatedManagerWrapper):
    """
    Wraps a many related manager (see RelatedManagerWrapper for details)
    """
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
        try:
            return self.instance._prefetched_objects_cache[self._get_cache_name()]
        except(AttributeError, KeyError):
            pass
        return super().all()

    def create(self, *args, **kwargs):
        raise NotImplementedError


class QuerySetWrapper(BaseQueryWrapper):
    """
    Wraps a queryset.
    """
    def _get_created_objects(self, get_foreign_objects=True):
        """
        Get ModelInstanceWrapper instance for all matched created objects.
        """
        return (self._changeset.get_created_object(self._obj.model, pk, get_foreign_objects=get_foreign_objects)
                for pk in sorted(self._created_pks))

    def _get_cached_result(self):
        """
        Get results, make sure prefetch is prefetching and so on.
        """
        obj = self._obj
        obj._prefetch_done = True
        obj._fetch_all()

        result = [self._wrap_instance(instance) for instance in obj._result_cache]
        obj._result_cache = result
        obj._prefetch_done = False
        obj._fetch_all()

        result += list(self._get_created_objects())

        for extra in self._extra:
            # implementing the extra() call for prefetch_related
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
                raise NotImplementedError('Cannot do extra() for ' + extra)

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
        # prefetch_related will try to set this property
        # it has to overwrite our final result because it already contains the created objects
        self.__dict__['_cached_result'] = value

    def __iter__(self):
        return iter(self._cached_result)

    def iterator(self):
        return iter(chain(
            (self._wrap_instance(instance) for instance in self._obj.iterator()),
            self._get_created_objects(),
        ))

    def __len__(self):
        return len(self._cached_result)

    def delete(self):
        for obj in self:
            obj.delete()

    @property
    def _iterable_class(self):
        return self._obj._iterable_class
