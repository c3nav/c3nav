import functools
from contextlib import contextmanager
from functools import cached_property

from django.db.models import Manager, Model, Prefetch, Q
from django.shortcuts import get_object_or_404

try:
    from asgiref.local import Local as LocalContext
except ImportError:
    from threading import local as LocalContext


class EditorQuerySet:
    _prefetch_related_lookups = True

    def __init__(self, model, qs=None, filters=(), prefetch_related=(), select_related=(),
                 order_by=(), defer=(), only=(), values=(), values_list_flat=None):
        self.model = model
        self._qs = model.objects.all() if qs is None else qs
        self._filters = filters
        self._prefetch_related = prefetch_related
        self._select_related = select_related
        self._order_by = order_by
        self._defer = defer
        self._only = only
        self._values = values
        self._values_list_flat = values_list_flat

    @classmethod
    def from_potential_manager(cls, base):
        if hasattr(base, 'through'):
            return cls(base.model).filter(**{base.query_field_name: base.instance})
        elif isinstance(base, Manager) and hasattr(base, 'instance'):
            return cls(base.model).filter(**{base.field.name: base.instance})
        elif issubclass(base, Model):
            return cls(base)
        else:
            raise TypeError

    def _chain(self, **kwargs):
        return EditorQuerySet(**{
            **dict(
                model=self.model,
                qs=self._qs,
                filters=self._filters,
                prefetch_related=self._prefetch_related,
                select_related=self._select_related,
                order_by=self._order_by,
                defer=self._defer,
                only=self._only,
                values=self._values,
                values_list_flat=self._values_list_flat,
            ),
            **kwargs
        })

    def filter(self, *args, **kwargs):
        return self._chain(
            qs=self._qs.filter(*args, **kwargs),
            filters=self._filters + (Q(*args, **kwargs),),
        )

    def exclude(self, *args, **kwargs):
        return self._chain(
            qs=self._qs.exclude(*args, **kwargs),
            filters=self._filters + (~Q(*args, **kwargs),),
        )

    def select_related(self, *args):
        return self._chain(
            qs=self._qs.select_related(*args),
            select_related=self._select_related + tuple(args),
        )

    def prefetch_related(self, *args):

        return self._chain(
            qs=self._qs.prefetch_related(*tuple(
                (Prefetch(
                    arg.prefetch_through,
                    arg.queryset._qs,  # todo: check that this is an EditorQuerySet
                    arg.to_attr
                ) if isinstance(arg, Prefetch) else arg) for arg in args)),
            prefetch_related=self._prefetch_related + tuple(args),
        )

    def order_by(self, *args):
        return self._chain(
            qs=self._qs.order_by(*args),
            order_by=tuple(args),
        )

    def defer(self, *args):
        return self._chain(
            qs=self._qs.defer(*args),
            defer=self._defer + tuple(args),
        )

    def only(self, *args):
        return self._chain(
            qs=self._qs.defer(*args),
            only=self._only + tuple(args),
        )

    def values(self, *args):
        return self._chain(
            qs=self._qs.values(*args),
            values=self._values + tuple(args),
        )

    def all(self):
        return self._chain(
            qs=self._qs.all(),
        )

    def values_list(self, *args, flat=False):
        return self._chain(
            qs=self._qs.values_list(*args, flat=flat),
            values_list_flat=bool(flat),
        )

    @cached_property
    def _results(self):
        with EditWrapper.allow_query():
            return tuple(self._qs)

    def __iter__(self):
        # todo: disallow database queries outside of this
        # todo: manipulate results
        yield from self._results

    def get_or_404(self, *args, **kwargs):
        # todo: manipulate results
        with EditWrapper.allow_query():
            return get_object_or_404(self._qs, *args, **kwargs)

    def count(self):
        # todo: manipulate results
        with EditWrapper.allow_query():
            return self._qs.count()

    def first(self):
        # todo: manipulate results
        with EditWrapper.allow_query():
            return self._qs.first()

    def last(self):
        # todo: manipulate results
        with EditWrapper.allow_query():
            return self._qs.last()


class EditWrapper():
    _ctx = LocalContext()

    @classmethod
    def queryset(self, base):
        return EditorQuerySet.from_potential_manager(base)

    @classmethod
    def enable(cls):
        def inner_wrapper(func):
            @functools.wraps(func)
            def wrapped_func(*args, **kwargs):
                if cls.get_active():
                    raise TypeError
                cls._ctx.active = True
                try:
                    cls._ctx.changeset = args[0].changeset
                except AttributeError:
                    cls._ctx.changeset = args[1].changeset
                try:
                    result = func(*args, **kwargs)
                finally:
                    cls._ctx.active = False
                    cls._ctx.changeset = None
                return result
            return wrapped_func
        return inner_wrapper

    @classmethod
    @contextmanager
    def allow_query(cls):
        if not cls.get_active():
            raise TypeError
        if cls.get_in_query():
            raise TypeError
        cls._ctx.in_query = True
        try:
            yield
        finally:
            cls._ctx.in_query = False

    @classmethod
    def get_active(cls):
        return getattr(cls._ctx, 'active', False)

    @classmethod
    def get_in_query(cls):
        return getattr(cls._ctx, 'in_query', False)


class EditorDatabaseRouter:
    def db_for_read(self, model, **hints):
        if model._meta.app_label == 'mapdata' and EditWrapper.get_active() and not EditWrapper.get_in_query():
            raise TypeError('Direct database query to %r not allowed' % model)
        return None

    def db_for_write(self, model, **hints):
        if model._meta.app_label == 'mapdata' and EditWrapper.get_active() and not EditWrapper.get_in_query():
            raise TypeError('Direct database query to %r not allowed' % model)
        return None

    def allow_relation(self, obj1, obj2, **hints):
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        return None
