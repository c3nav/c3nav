import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cached_property
from typing import Protocol

from django.contrib.auth.models import User

from c3nav.control.models import UserSpaceAccess
from c3nav.mapdata.models import MapUpdate
from c3nav.mapdata.models.access import AccessPermission, AccessRestriction

try:
    from asgiref.local import Local as LocalContext
except ImportError:
    from threading import local as LocalContext


class MapPermissions(Protocol):
    access_restrictions: set[int]  # accessible access permissions
    spaces: dict[int, bool]   # accessible space geometry
    all_base_mapdata: bool  # all spaces the users can access, with value True if they may also edit them
    view_sources: bool  # can view sources


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
        return UserSpaceAccess.get_for_user(self.request.user)

    @cached_property
    def all_base_mapdata(self):
        return self.request.user_permissions.base_mapdata_access

    @cached_property
    def sources_access(self):
        # todo: tbh, this should just go via access permissions, no need to introduce this
        return self.request.user_permissions.view_sources


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
        return UserSpaceAccess.get_for_user(self.user)

    @cached_property
    def all_base_mapdata(self):
        return self.user.permissions.base_mapdata_access

    @cached_property
    def sources_access(self):
        # todo: tbh, this should just go via access permissions, no need to introduce this
        return self.user.permissions.view_sources


@dataclass(frozen=True)  # frozen seemed like a good idea but we could change it – if we rely on it, edit this comment
class ManualMapPermissions:
    access_restrictions: set[int]
    spaces: dict[int, bool]
    all_base_mapdata: bool
    view_sources: bool

    @classmethod
    def get_full_access(cls):
        return cls(
            access_restrictions=AccessRestriction.get_all(),
            spaces={},
            all_base_mapdata=True,
            view_sources=True,
        )

    @classmethod
    def get_public_access(cls):
        return cls(
            access_restrictions=AccessRestriction.get_all_public(),
            spaces={},
            all_base_mapdata=False,
            view_sources=False,
        )


class MapPermissionContext:
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
            warnings.warn('No map permission context set, defaulting to public context.', RuntimeWarning)
            return ManualMapPermissions.get_public_access()
        return self._active.value

    @contextmanager
    def override(self, value: MapPermissions):
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
    def cache_key_without_update(self):
        # todo: we definitely want to find a way to shorten this
        return (
            '-'.join(str(i) for i in sorted(self.access_restrictions) or '0') + ":"
            + ('a' if self.all_base_mapdata else ('-'.join(str(i) for i in sorted(self.access_restrictions) or '0')))
            + f":{self.view_sources:d}"
        )

    @property
    def cache_key(self):
        return f"{MapUpdate.current_cache_key()}:{self.cache_key_without_update}"

    def etag_func(self, request):
        return self.cache_key


active_map_permissions = MapPermissionContext()