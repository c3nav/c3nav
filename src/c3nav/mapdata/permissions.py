import operator
import warnings
from abc import abstractmethod, ABC
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cached_property, lru_cache, reduce
from typing import Protocol, Sequence, Iterator, Callable, Any, Mapping, NamedTuple, Optional

from django.contrib.auth.models import User
from django.utils.functional import lazy

from c3nav.mapdata.models.access import AccessPermission, AccessRestriction, AccessRestrictionLogicMixin

try:
    from asgiref.local import Local as LocalContext
except ImportError:
    from threading import local as LocalContext


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


class CachedMapPermissionsFromX(type):
    def __call__(cls, x):
        if not hasattr(x, '_map_permissions_cache'):
            x._map_permissions_cache = super().__call__(x)
        return x._map_permissions_cache


class MapPermissionsFromRequest(metaclass=CachedMapPermissionsFromX):
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


class MapPermissionsFromUser(metaclass=CachedMapPermissionsFromX):
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
class ManualMapPermissions:
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
            warnings.warn('No map permission context set, defaulting to public context.', DeprecationWarning)
            return ManualMapPermissions.get_public_access()
        return self._active.value

    @cached_property
    def disable_access_checks(self):
        return FullAccessContextManager(self)

    @contextmanager
    def override(self, value: MapPermissions):
        # todo: don't use this… usually
        prev_value = getattr(self._active, "value", None)
        self.set_value(value)
        yield
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


class BaseMapPermissionFiltered[T](ABC):
    @abstractmethod
    def _get_for_permissions(self, full: bool, permissions: set[int]) -> T:
        pass

    @property
    @abstractmethod
    def _all_restrictions(self) -> frozenset[int]:
        pass

    @cached_property
    def _get(self) -> Callable[[], T]:
        # this is a hack to have one lru_cache per instance
        # todo: this probably is still slower than it needs to be, because of the set operation?
        return lru_cache(maxsize=16)(lambda: self._get_for_permissions(
            full=active_map_permissions.full,
            permissions=active_map_permissions.access_restrictions - self._all_restrictions
        ))

    def __getstate__(self):
        result = self.__dict__.copy()
        result.pop('_get', None)
        return result


class LazyMapPermissionFilteredMapping[KT, VT: AccessRestrictionLogicMixin](Mapping[KT, VT],
                                                                            BaseMapPermissionFiltered[dict[KT, VT]]):
    """
    Wraps a mapping of AccessRestrictionLogicMixin objects.
    Acts like a mapping (like dict) but will filter objects based on the active map permissions.
    Caches the last 16 configurations.
    """
    def __init__(self, data: dict[KT, VT]):
        self._data = data

    def __len__(self) -> int:
        return len(self._get())

    def _get_for_permissions(self, full: bool, permissions: set[int]) -> dict[KT, VT]:
        if full:
            return self._data.copy()
        return {key: value for key, value in self._data.items()
                if not (value.effective_access_restrictions - permissions)}

    @cached_property
    def _all_restrictions(self) -> frozenset[int]:
        return reduce(operator.or_, (item.effective_access_restrictions for item in self._data.values()), frozenset())

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


class BaseLazyMapPermissionFilteredSequence[T](Sequence[T], BaseMapPermissionFiltered[tuple[T, ...]], ABC):
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


class LazyMapPermissionFilteredSequence[T: AccessRestrictionLogicMixin](BaseLazyMapPermissionFilteredSequence[T]):
    """
    Wraps a sequence of AccessRestrictionLogicMixin objects.
    Acts like a sequence (like list, tuple, ...) but will filter objects based on the active map permissions.
    Caches the last 16 configurations.
    """
    def __init__(self, data: Sequence[T]):
        self._data = data

    def _get_for_permissions(self, full: bool, permissions: set[int]) -> tuple[T, ...]:
        if full:
            return tuple(self._data)
        return tuple(item for item in self._data
                     if not (item.effective_access_restrictions - permissions))

    @cached_property
    def _all_restrictions(self) -> frozenset[int]:
        return reduce(operator.or_, (item.effective_access_restrictions for item in self._data), frozenset())


class MapPermissionTaggedItem[T](NamedTuple):
    value: T
    access_restrictions: frozenset[int]


class LazyMapPermissionFilteredTaggedSequence[T](BaseLazyMapPermissionFilteredSequence[T]):
    """
    Wraps a sequence of MapPermissionTaggedItem[T] objects.
    Acts like a Sequence[T] (like list, tuple, ...) but will filter objects based on the active map permissions.
    Caches the last 16 configurations.
    """
    def __init__(self, data: Sequence[MapPermissionTaggedItem[T]]):
        self._data = data

    def _get_for_permissions(self, full: bool, permissions: set[int]) -> tuple[T, ...]:
        if full:
            return tuple(item.value for item in self._data)
        return tuple(item.value for item in self._data
                     if not (item.access_restrictions - permissions))

    @cached_property
    def _all_restrictions(self) -> frozenset[int]:
        return reduce(operator.or_, (item.access_restrictions for item in self._data), frozenset())


class LazyMapPermissionFilteredTaggedValue[T, DT](BaseMapPermissionFiltered[T | DT]):
    """
    Wraps a sequence of MapPermissionTaggedItem[T] objects.
    Allows you to get the first visible item based on the active map permissions.
    Caches the last 16 configurations.
    """
    def __init__(self, data: Sequence[MapPermissionTaggedItem[T]], *, default: DT = None):
        self._data = data
        self._default = default

    def _get_for_permissions(self, full: bool, permissions: set[int]) -> T | DT:
        try:
            if full:
                return next(iter(item.value for item in self._data))
            return next(iter(item.value for item in self._data
                             if not (item.access_restrictions - permissions)))
        except StopIteration:
            return self._default

    @cached_property
    def _all_restrictions(self) -> frozenset[int]:
        return reduce(operator.or_, (item.access_restrictions for item in self._data), frozenset())

    @cached_property
    def get(self) -> Callable[[], T | DT]:
        # hack to make the actual _get call lazy
        return lazy(self._get, dict)