import operator
import sys
import warnings
from abc import abstractmethod, ABC
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from functools import cached_property, lru_cache, reduce
from typing import Protocol, Sequence, Iterator, Callable, Any, Mapping, NamedTuple, Generator, Iterable, \
    overload, TypeAlias

from django.apps.registry import apps
from django.contrib.auth.models import User

from c3nav.mapdata.models.access import AccessPermission, AccessRestriction, AccessRestrictionLogicMixin

try:
    from asgiref.local import Local as LocalContext
except ImportError:
    from threading import local as LocalContext


class FullAccessTo(Enum):
    RESTRICTIONS = "restrictions"
    SPACES = "spaces"


class SpacePermission(NamedTuple):
    space_id: int


PermissionsAsSet: TypeAlias = frozenset[FullAccessTo | SpacePermission | int]


class MapPermissions(Protocol):
    @property
    def access_restrictions(self) -> set[int]:
        """
        accessible access permissions
        """
        pass

    @property
    def spaces(self) -> dict[int, bool]:
        """
        accessible space geometry
        """
        pass

    @property
    def all_base_mapdata(self) -> bool:
        """
        all spaces the users can access, with value True if they may also edit them
        """
        pass

    @property
    def view_sources(self) -> bool:
        """
        can view sources
        """
        pass

    @property
    def full(self) ->  bool:
        """
        full access – disable filtering
        """
        pass

    @property
    def as_set(self) -> PermissionsAsSet:
        pass


class MapPermissionsAsSet:
    @cached_property
    def as_set(self) -> PermissionsAsSet:
        return frozenset((
            *((FullAccessTo.RESTRICTIONS,) if self.full else self.access_restrictions),
            *((FullAccessTo.SPACES,) if self.all_base_mapdata else (SpacePermission(i) for i in self.spaces)),
        ))


class CachedMapPermissionsFromX(type):
    def __call__(cls, x):
        if not hasattr(x, '_map_permissions_cache'):
            x._map_permissions_cache = super().__call__(x)
        return x._map_permissions_cache


class MapPermissionsFromRequest(MapPermissionsAsSet, metaclass=CachedMapPermissionsFromX):
    """
    Get map permissions for this request.
    If called twice on the same request object, it will return a cached result.

    implements MapPermissions (see above)
    """
    def __init__(self, request):
        self.request = request

    @cached_property
    def access_restrictions(self) -> set[int]:
        return AccessPermission.get_for_request(self.request)

    @cached_property
    def spaces(self) -> dict[int, bool]:
        from c3nav.control.models import UserSpaceAccess
        return UserSpaceAccess.get_for_user(self.request.user)

    @cached_property
    def all_base_mapdata(self):
        return self.request.user_permissions.base_mapdata_access

    @cached_property
    def view_sources(self):
        # todo: tbh, this should just go via access permissions, no need to introduce this
        return self.request.user_permissions.sources_access

    @cached_property
    def full(self):
        return self.request.user.is_superuser


class MapPermissionsFromUser(MapPermissionsAsSet, metaclass=CachedMapPermissionsFromX):
    """
    Get map permissions for this user.
    If called twice on the same request object, it will return a cached result.

    Implements MapPermissions (see above)
    """
    def __init__(self, user: User):
        self.user = user

    @cached_property
    def access_restrictions(self) -> set[int]:
        return AccessPermission.get_for_user(self.user)

    @cached_property
    def spaces(self) -> dict[int, bool]:
        from c3nav.control.models import UserSpaceAccess
        return UserSpaceAccess.get_for_user(self.user)

    @cached_property
    def all_base_mapdata(self):
        return self.user.permissions.base_mapdata_access

    @cached_property
    def view_sources(self):
        # todo: tbh, this should just go via access permissions, no need to introduce this
        return self.user.permissions.sources_access

    @cached_property
    def full(self):
        return self.user.is_superuser


@dataclass(frozen=True)  # frozen seemed like a good idea but we could change it – if we rely on it, edit this comment
class ManualMapPermissions(MapPermissionsAsSet):
    access_restrictions: set[int]
    spaces: dict[int, bool]
    all_base_mapdata: bool
    view_sources: bool
    full: bool = False

    @classmethod
    def get_full_access(cls):
        return cls(
            access_restrictions=AccessRestriction.get_all(),
            spaces={},
            all_base_mapdata=True,
            view_sources=True,
            full=True,
        )

    @classmethod
    def get_public_access(cls):
        return cls(
            access_restrictions=AccessRestriction.get_all_public(),
            spaces={},
            all_base_mapdata=False,
            view_sources=False,
        )


class FullAccessContextManager:
    def __init__(self, ctx):
        self.ctx = ctx

    def __call__(self):
        return self.ctx.override(ManualMapPermissions.get_full_access())

    def __bool__(self):
        raise ValueError('This should not happen!')


class MapPermissionContext(MapPermissions):
    """
    This is great, but it is also a controversial design choice.
    Having global context like this is a bit intransparent.
    However, despite all the critique, django does it, too, for translations.

    So, here's when and how to use this:

    - If you have code that needs access to the map Permisisons, consider
      allowing passing an argument, especially when it feels likely that
      this code might be used outside of requests.
    - When you use it, the method name should and the documentation/docstring MUST acknowledge it.
    - The only exception is code that is mainly used to serialize objects. We use a lot of properties there.
    """
    def __init__(self):
        self._active = LocalContext()

    def set_value(self, value: MapPermissions):
        self._active.value = value

    def unset_value(self):
        if hasattr(self._active, "value"):
            del self._active.value

    def get_value(self) -> MapPermissions:
        if not hasattr(self._active, "value"):
            if not apps.ready:
                return ManualMapPermissions.get_full_access()

            # todo: this should fail, absolutely
            if 'manage.py' in sys.argv and 'runserver' not in sys.argv:
                warnings.warn('No map permission context set, defaulting to full context.', DeprecationWarning)
                return ManualMapPermissions.get_full_access()

            warnings.warn('No map permission context set, defaulting to public context.', DeprecationWarning)
            return ManualMapPermissions.get_public_access()
        return self._active.value

    @cached_property
    def disable_access_checks(self) -> FullAccessContextManager:
        return FullAccessContextManager(self)

    @contextmanager
    def override(self, value: MapPermissions):
        # Apparently asgiref.local cannot be trusted to actually keep the data local per-request?
        # See: https://github.com/django/asgiref/issues/473
        # TODO: If we can't trust it, we want to get rid of it.
        # However, the problem remains that the main issue, needing request isolation, remains.
        prev_value = getattr(self._active, "value", None)
        self.set_value(value)
        yield
        if self.get_value() != value:
            raise ValueError(f'SOMETHING IS VERY WRONG, SECURITY ISSUE {self.get_value()} {value}')
        if prev_value is None:
            self.unset_value()
        else:
            self.set_value(prev_value)

    @property
    def access_restrictions(self) -> set[int]:
        return self.get_value().access_restrictions

    @property
    def spaces(self) -> dict[int, bool]:
        return self.get_value().spaces

    @property
    def all_base_mapdata(self) -> bool:
        return self.get_value().all_base_mapdata

    @property
    def view_sources(self) -> bool:
        return self.get_value().view_sources

    @property
    def full(self) -> bool:
        return self.get_value().full

    @property
    def as_set(self) -> PermissionsAsSet:
        return self.get_value().as_set

    @property
    def permissions_cache_key(self) -> str:
        # todo: we definitely want to find a way to shorten this
        return (
            '-'.join(str(i) for i in sorted(self.access_restrictions) or '0')
            + f":{self.view_sources:d}"  # todo: get rid of view_sources
        )

    @property
    def base_mapdata_cache_key(self) -> str:
        return 'a' if self.all_base_mapdata else ('-'.join(str(i) for i in sorted(self.spaces) or '0'))


active_map_permissions = MapPermissionContext()


class BaseMapPermissionGuarded[T](ABC):
    """
    Base class for a wrapper that guards data based on map permissions.
    """
    @abstractmethod
    def _get_for_permissions(self, permissions_as_set: PermissionsAsSet) -> T:
        pass

    @cached_property
    def _cached_get(self) -> Callable[[PermissionsAsSet], T]:
        # this is a hack to have one lru_cache per instance
        return lru_cache(maxsize=16)(self._get_for_permissions)

    @property
    @abstractmethod
    def _relevant_permissions(self) -> PermissionsAsSet:
        """
        All permissions that may affect the result here.
        """
        pass

    def _get_only_relevant_permissions(self, permissions_as_set: PermissionsAsSet) -> PermissionsAsSet:
        if FullAccessTo.RESTRICTIONS in permissions_as_set:
            # necessary, otherwise we have massive queries during cache buildup
            return permissions_as_set
        return self._relevant_permissions & permissions_as_set

    @cached_property
    def _cached_get_only_relevant_permissions(self) -> Callable[[PermissionsAsSet], PermissionsAsSet]:
        # this is a hack to have one lru_cache per instance
        return lru_cache(maxsize=16)(self._get_only_relevant_permissions)

    @property
    @abstractmethod
    def _minimum_permissions(self) -> tuple[PermissionsAsSet, ...]:
        """
        Possible minimum permissions to get any result.
        If the user doesn't have all of at least one of these, the result will be empty.
        """
        pass

    def _has_minimum_permissions(self, permissions_as_set: PermissionsAsSet) -> bool:
        if FullAccessTo.RESTRICTIONS in permissions_as_set:
            # necessary, otherwise we have massive queries during cache buildup
            return True
        return not self._minimum_permissions or any((item <= permissions_as_set) for item in self._minimum_permissions)

    def _get(self) -> T:
        return self._cached_get(self._cached_get_only_relevant_permissions(active_map_permissions.as_set))

    def __getstate__(self):
        result = self.__dict__.copy()
        result.pop('_cached_get', None)
        result.pop('_cached_get_only_relevant_permissions', None)
        return result


class MapPermissionGuardedMapping[KT, VT: AccessRestrictionLogicMixin](Mapping[KT, VT],
                                                                       BaseMapPermissionGuarded[dict[KT, VT]]):
    """
    Wraps a mapping of AccessRestrictionLogicMixin objects.
    Acts like a mapping (like dict) but will filter objects based on the active map permissions.
    Caches the last 16 configurations.
    """
    def __init__(self, data: dict[KT, VT]):
        self._data = data

    def __len__(self) -> int:
        return len(self._get())

    def _get_for_permissions(self, permissions_as_set: PermissionsAsSet) -> dict[KT, VT]:
        if FullAccessTo.RESTRICTIONS in permissions_as_set:
            return self._data.copy()
        if self._has_minimum_permissions(permissions_as_set):
            return {}
        return {key: value for key, value in self._data.items()
                if not (value.effective_access_restrictions - permissions_as_set)}

    @cached_property
    def _relevant_permissions(self) -> PermissionsAsSet:
        return reduce(operator.or_, (item.effective_access_restrictions for item in self._data.values()),
                      frozenset((FullAccessTo.RESTRICTIONS, )))

    @cached_property
    def _minimum_permissions(self) -> tuple[PermissionsAsSet, ...]:
        """
        Possible minimum permissions to get any result.
        If the user doesn't have all of at least one of these, the result will be empty.
        """
        common_permissions: PermissionsAsSet = reduce(  # noqa
            operator.and_, (item.effective_access_restrictions for item in self._data.values()), frozenset()
        )
        if not common_permissions:
            return ()
        return (
            frozenset((FullAccessTo.RESTRICTIONS,)),
            common_permissions,
        )

    def __iter__(self) -> Iterator[KT]:
        return iter(self._get())

    def __getitem__(self, key: KT):
        value = self._data[key]
        if value.effective_access_restrictions - active_map_permissions.access_restrictions:
           raise KeyError(key)
        return value

    def get(self, key: KT, default=None):
        value = self._data.get(key, default)
        if value is not None and value.effective_access_restrictions - active_map_permissions.access_restrictions:
            return default
        return value

    def items(self):
        return self._get().items()

    def keys(self):
        return self._get().keys()

    def values(self):
        return self._get().values()

    def __contains__(self, item) -> bool:
        return item in self._get()


class BaseMapPermissionGuardedSequence[T](Sequence[T], BaseMapPermissionGuarded[tuple[T, ...]], ABC):
    """
    Base class for a wrapper that guards a sequence based on map permissions.
    """
    _data: Sequence

    def __len__(self) -> int:
        return len(self._get())

    def __getitem__(self, item: int):
        if isinstance(item, slice):
            raise TypeError('slicing a lazy filtered list would have confusing behavior, sorry.')
        return self._get()[item]

    def __iter__(self) -> Iterator[T]:
        return iter(self._get())

    def __contains__(self, item) -> bool:
        return item in self._get()

    def index(self, value: Any, start: int = 0, stop: int = ...) -> int:
        i = self._get().index(value, start, stop)
        if i < start or (stop is not ... and i >= stop):
            raise ValueError
        return i

    def count(self, value: Any) -> int:
        return self._get().count(value)

    def __reversed__(self) -> Iterator[T]:
        return iter(reversed(self._get()))


class LazyMapPermissionFilteredSequence[T: AccessRestrictionLogicMixin](BaseMapPermissionGuardedSequence[T]):
    """
    Wraps a sequence of AccessRestrictionLogicMixin objects.
    Acts like a sequence (like list, tuple, ...) but will filter objects based on the active map permissions.
    Caches the last 16 configurations.
    """
    def __init__(self, data: Sequence[T]):
        self._data = data

    def _get_for_permissions(self, permissions_as_set: PermissionsAsSet) -> tuple[T, ...]:
        if self._has_minimum_permissions(permissions_as_set):
            return ()
        if FullAccessTo.RESTRICTIONS in permissions_as_set:
            return tuple(self._data)
        return tuple(item for item in self._data
                     if not (item.effective_access_restrictions - permissions_as_set))

    @cached_property
    def _relevant_permissions(self) -> PermissionsAsSet:
        return reduce(operator.or_, (item.effective_access_restrictions for item in self._data), frozenset())

    @cached_property
    def _minimum_permissions(self) -> tuple[PermissionsAsSet, ...]:
        common_permissions: PermissionsAsSet = reduce(
            operator.and_, (item.effective_access_restrictions for item in self._data), frozenset()
        )
        if not common_permissions:
            return ()
        return (
            frozenset((FullAccessTo.RESTRICTIONS,)),
            common_permissions,
        )

    def __repr__(self):
        return f"LazyMapPermissionFilteredSequence({self._data})"


class MapPermissionTaggedItem[T](NamedTuple):
    """
    Tags a value with access permissions
    """
    value: T
    access_restrictions: frozenset[int]

    @staticmethod
    def skip_redundant_presorted[T](values: Iterable["MapPermissionTaggedItem[T]"]) -> Generator["MapPermissionTaggedItem[T]"]:
        """
        Yield every item unless it was preceeded by one with the same value and a subset of access restrictions.
        Only works if identical values are all next to each other. Use skip_redundant() otherwise.
        """
        last_value = None
        done = []
        for item in values:
            if item.value != last_value:
                done = []
                last_value = item.value
            if any((d <= item.access_restrictions) for d in done):
                # skip restriction supersets of other instances of the same value
                continue
            done.append(item.access_restrictions)
            yield item

    @staticmethod
    def skip_redundant[T](values: Iterable["MapPermissionTaggedItem[T]"],
                          *, reverse: bool = False) -> Generator["MapPermissionTaggedItem[T]"]:
        """
        Sort items by value – ascending by default, descending if reverse=True
        Then, yield all items that unless there is one with the same value and a subset of access restrictions.
        """
        values = sorted(values, key=lambda item: (item.value * (-1 if reverse else 1), len(item.access_restrictions)))
        yield from MapPermissionTaggedItem.skip_redundant_presorted(values)

    @staticmethod
    def add_restrictions_and_skip_redundant[T](
            values: Iterable["MapPermissionTaggedItem[T]"],
            access_restrictions: frozenset[int]) -> Generator["MapPermissionTaggedItem[T]"]:
        """
        Expecting the items to presorted, add access restrictions to each one.
        Then, yield all items that unless there is one with the same value and a subset of access restrictions.
        """
        yield from MapPermissionTaggedItem.skip_redundant_presorted((
            MapPermissionTaggedItem(
                value=item.value,
                access_restrictions=item.access_restrictions | access_restrictions,
            ) for item in values
        ))


class MapPermissionGuardedTaggedSequence[T](BaseMapPermissionGuardedSequence[T]):
    """
    Wraps a sequence of MapPermissionTaggedItem[T] objects.
    Acts like a Sequence[T] (like list, tuple, ...) but will filter objects based on the active map permissions.
    Caches the last 16 configurations.
    """
    def __init__(self, data: Sequence[MapPermissionTaggedItem[T]]):
        self._data = data

    def _get_for_permissions(self, permissions_as_set: PermissionsAsSet) -> tuple[T, ...]:
        if self._has_minimum_permissions(permissions_as_set):
            return ()
        if FullAccessTo.RESTRICTIONS in permissions_as_set:
            return tuple(item.value for item in self._data)
        return tuple(item.value for item in self._data
                     if not (item.access_restrictions - permissions_as_set))

    @cached_property
    def _relevant_permissions(self) -> PermissionsAsSet:
        return reduce(operator.or_, (item.access_restrictions for item in self._data),
                      frozenset((FullAccessTo.RESTRICTIONS, )))

    @cached_property
    def _minimum_permissions(self) -> tuple[PermissionsAsSet, ...]:
        common_permissions: PermissionsAsSet = reduce(  # noqa
            operator.and_, (item._relevant_permissions for item in self._data), frozenset()
        )
        if not common_permissions:
            return ()
        return (
            frozenset((FullAccessTo.RESTRICTIONS,)),
            common_permissions,
        )

    def __repr__(self):
        return f"LazyMapPermissionFilteredTaggedSequence({self._data})"


class BaseMapPermissionGuardedValue[T](BaseMapPermissionGuarded[T], ABC):
    """
    Base class for a wrapper that guards a single value based on map permissions.
    """
    @abstractmethod
    def get(self) -> T:
        pass


class MapPermissionGuardedTaggedValue[T, DT](BaseMapPermissionGuardedValue[T | DT]):
    """
    Wraps a sequence of MapPermissionTaggedItem[T] objects.
    Allows you to get the first visible item based on the active map permissions.
    Caches the last 16 configurations.
    """
    def __init__(self, data: Sequence[MapPermissionTaggedItem[T]], *, default: DT):
        self._data = data
        self._default = default

    def _get_for_permissions(self, permissions_as_set: PermissionsAsSet) -> T | DT:
        if self._has_minimum_permissions(permissions_as_set):
            return self._default
        try:
            if FullAccessTo.RESTRICTIONS in permissions_as_set:
                return next(iter(item.value for item in self._data))
            return next(iter(item.value for item in self._data
                             if not (item.access_restrictions - permissions_as_set)))
        except StopIteration:
            return self._default

    @cached_property
    def _relevant_permissions(self) -> PermissionsAsSet:
        """ All permissions that may affect the result here. """
        return reduce(operator.or_, (item.access_restrictions for item in self._data),
                      frozenset((FullAccessTo.RESTRICTIONS, )))

    @cached_property
    def _minimum_permissions(self) -> tuple[PermissionsAsSet, ...]:
        common_permissions: PermissionsAsSet = reduce(  # noqa
            operator.and_, (item._relevant_permissions for item in self._data), frozenset()
        )
        if not common_permissions:
            return ()
        return (
            frozenset((FullAccessTo.RESTRICTIONS,)),
            common_permissions,
        )

    def get(self) -> T | DT:
        return self._get()

    def __getstate__(self):
        result = super().__getstate__()
        result.pop('get', None)
        return result

    def __repr__(self):
        return f"LazyMapPermissionFilteredTaggedValue({self._data}, default={self._default})"


class MapPermissionsMaskedTaggedValue[T, MT = T](BaseMapPermissionGuardedValue[T | MT]):
    """
    Wraps two LazyPermissionValue instances, deliver them the private or masked one based on the user's space permissions.
    """
    @overload
    def __init__(self, *, value: BaseMapPermissionGuardedValue[T], masked_value: BaseMapPermissionGuardedValue[MT], space_id: int):
        pass

    @overload
    def __init__(self, value: BaseMapPermissionGuardedValue[T]):
        pass

    def __init__(self, value: BaseMapPermissionGuardedValue[T], *, masked_value: BaseMapPermissionGuardedValue[MT] | None = None,
                 space_id: int | None = None):
        self._value = value
        self._masked_value = masked_value
        self._space_id = space_id

    @cached_property
    def _relevant_permissions(self) -> PermissionsAsSet:
        return (
            self._value._relevant_permissions
            | (frozenset() if self._masked_value is None
               else {FullAccessTo.SPACES, SpacePermission(self._space_id), *self._masked_value._relevant_permissions})
        )

    @cached_property
    def _minimum_permissions(self) -> tuple[PermissionsAsSet, ...]:
        if not self._value._minimum_permissions:
            if self._masked_value is None or not self._masked_value._minimum_permissions:
                return ()
        return tuple(filter(None, (
            *self._value._minimum_permissions,
            *(() if self._masked_value is None else self._masked_value._minimum_permissions),
        )))

    def _get_for_permissions(self, permissions_as_set: PermissionsAsSet) -> T | MT:
        if self._masked_value is None or {FullAccessTo.SPACES, SpacePermission(self._space_id)} & permissions_as_set:
            return self._value.get()
        return self._masked_value.get()

    def get(self) -> T | MT:
        return self._get()

    def __repr__(self):
        if self._space_id is None:
            return f"LazySpacePermissionMaskedValue({self._value})"
        else:
            return (f"LazySpacePermissionMaskedValue({self._value}, masked_value={self._value}, "
                    f"space_id={self._space_id})")


class MapPermissionGuardedTaggedValueSequence[T](BaseMapPermissionGuardedSequence[T]):
    """
    Wraps a sequence of LazyPermissionValue[T] objects.
    Acts like a Sequence[T] (like list, tuple, ...) but will filter objects based on the active map permissions.
    If an item evaluates to None, it will be skipped.
    Caches the last 16 configurations.
    """
    def __init__(self, data: Sequence[BaseMapPermissionGuardedValue[T | None]]):
        self._data: Sequence[BaseMapPermissionGuardedValue[T | None]] = data

    def _get_for_permissions(self, permissions_as_set: PermissionsAsSet) -> tuple[T, ...]:
        if not self._has_minimum_permissions(permissions_as_set):
            return ()
        if FullAccessTo.RESTRICTIONS in permissions_as_set:
            return tuple(filter(None, (item.get() for item in self._data)))
        return tuple(filter(None, (item.get() for item in self._data)))

    @cached_property
    def _relevant_permissions(self) -> PermissionsAsSet:
        # noinspection PyProtectedMember
        return reduce(operator.or_, (item._relevant_permissions for item in self._data), frozenset())

    @cached_property
    def _minimum_permissions(self) -> tuple[PermissionsAsSet, ...]:
        common_permissions: PermissionsAsSet = reduce(  # noqa
            operator.and_, (item._relevant_permissions for item in self._data), frozenset()
        )
        if not common_permissions:
            return ()
        return (
            # we don't know if it's filtered by restrictions or spaces but if you don't have the
            # common relevant permissions, you'll need one of these to see anything, that's for sure
            frozenset((FullAccessTo.RESTRICTIONS,)),
            frozenset((FullAccessTo.SPACES,)),
            common_permissions,
        )

    def __repr__(self):
        return f"LazyMapPermissionFilteredTaggedValueSequence({self._data})"
