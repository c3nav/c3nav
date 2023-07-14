from functools import cached_property

from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404


class EditorQuerySet:
    _prefetch_related_lookups = True

    def __init__(self, model, related_name=None, qs=None, filters=(), prefetch_related=(), select_related=(),
                 order_by=(), defer=(), only=(), values=()):
        self.model = model
        if qs is None:
            if related_name is None:
                self._qs = model.objects.all()
            else:
                from pprint import pprint
                pprint(model._meta.get_field(related_name))
        else:
            self._qs = qs
        self._filters = filters
        self._prefetch_related = prefetch_related
        self._select_related = select_related
        self._order_by = order_by
        self._defer = defer
        self._only = only
        self._values = values

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

    @cached_property
    def _results(self):
        return tuple(self._qs)

    def __iter__(self):
        # todo: disallow database queries outside of this
        # todo: manipulate results
        yield from self._results

    def values_list(self, *args, flat=False):
        # todo: manipulate results
        return self._qs.values_list(*args, flat=flat)

    def get_or_404(self, *args, **kwargs):
        # todo: manipulate results
        return get_object_or_404(self._qs, *args, **kwargs)

    def count(self):
        # todo: manipulate results
        return self._qs.count()
