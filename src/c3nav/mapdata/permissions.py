import operator
import sys
import traceback
import warnings
from abc import abstractmethod, ABC
from collections import deque, defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import Enum
from functools import cached_property, lru_cache, reduce
from itertools import product
from typing import Protocol, Sequence, Iterator, Callable, Any, Mapping, NamedTuple, Generator, Iterable, \
    overload, TypeAlias, Union, Optional, Self

from django.apps.registry import apps
from django.contrib.auth.models import User
from pydantic_core import CoreSchema, core_schema, SchemaSerializer

from c3nav.mapdata.models.access import AccessPermission, AccessRestriction, AccessRestrictionLogicMixin
from c3nav.mapdata.utils.cache.compress import compress_sorted_list_of_int

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


class AccessRestrictionsEval(ABC):
    @abstractmethod
    def can_see(self, permissions_as_set: PermissionsAsSet) -> bool:
        raise NotImplementedError

    @abstractmethod
    def __or__(self, other) -> Self:
        raise NotImplementedError

    @abstractmethod
    def __and__(self, other) -> Self:
        raise NotImplementedError

    @abstractmethod
    def __sub__(self, other: frozenset[int]) -> Self:
        raise NotImplementedError

    @property
    @abstractmethod
    def relevant_permissions(self) -> frozenset[int]:
        raise NotImplementedError

    @property
    @abstractmethod
    def minimum_permissions(self) -> frozenset[int]:
        raise NotImplementedError

    @abstractmethod
    def simplify(self) -> Self:
        raise NotImplementedError

    @abstractmethod
    def flatten(self) -> frozenset[PermissionsAsSet]:
        raise NotImplementedError

    def __le__(self, other: Self) -> bool:
        """
        Does this eval imply the other one (so if this one applies, the other always will too)
        """
        if other.minimum_permissions - self.minimum_permissions:
            return False

        relevant_self = self - (self.relevant_permissions - other.relevant_permissions)
        return all(other.can_see(option) for option in relevant_self.simplify().flatten())

    def __ge__(self, other: Self) -> bool:
        """
        Does the other eval imply this one (so if the other one applies, this one always wil too)
        """
        return other <= self


# todo: this is so dumb! get pydantic to serialize this properly and more simply. it works for now but this is silly


class NoAccessRestrictionsCls(AccessRestrictionsEval):
    def can_see(self, permissions_as_set: PermissionsAsSet) -> bool:
        return True

    def __or__(self, other: AccessRestrictionsEval) -> Self:
        return self

    def __and__[T: AccessRestrictionsEval](self, other: T) -> T:
        return other

    def __sub__(self, other: frozenset[int]) -> Self:
        return self

    @property
    def relevant_permissions(self) -> frozenset[int]:
        return frozenset()

    @property
    def minimum_permissions(self) -> frozenset[int]:
        return frozenset()

    def simplify(self) -> Self:
        return self

    def flatten(self) -> frozenset[PermissionsAsSet]:
        return frozenset()

    def __repr__(self):
        return "NoAccessRestrictions"

    @classmethod
    def _validate(cls, value: Any) -> Self:
        return NoAccessRestrictions

    @classmethod
    def _serialize(cls, value: Any) -> None:
        return None

    schema = core_schema.none_schema()

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any=None, handler=None) -> CoreSchema:
        schema = core_schema.no_info_after_validator_function(
            cls._validate,
            core_schema.union_schema([core_schema.is_instance_schema(cls), cls.schema]),
            serialization=core_schema.plain_serializer_function_ser_schema(
                cls._serialize, info_arg=False, return_schema=cls.schema,
            ),
        )
        # confused? me too. it's needed because https://github.com/pydantic/pydantic/issues/7779
        cls.__pydantic_serializer__ = SchemaSerializer(schema)
        return schema


NoAccessRestrictions = NoAccessRestrictionsCls()


class InfiniteAccessRestrictionsCls:
    """
    An access restrictions eval compatible class that doesn't allow anyone to see anything.
    Only useful for constructing access restriction eval objects by __or__'ing this or so.
    """

    def __or__[T: AccessRestrictionsEval](self, other: T) -> T:
        return other

    def __and__(self, other: AccessRestrictionsEval) -> Self:
        return self

    def __repr__(self):
        return "InfiniteAccessRestrictions"


InifiniteAccessRestrictions = InfiniteAccessRestrictionsCls()


class AccessRestrictionsOneID:
    @classmethod
    def build(cls, access_restriction: int | None) -> Union[NoAccessRestrictionsCls, "AccessRestrictionsAllIDs"]:
        if access_restriction is None:
            return NoAccessRestrictions
        return AccessRestrictionsAllIDs(frozenset((access_restriction, )))


@dataclass(frozen=True, slots=True)
class AccessRestrictionsAllIDs(AccessRestrictionsEval):
    access_restrictions: frozenset[int]

    def can_see(self, permissions_as_set: PermissionsAsSet) -> bool:
        return not bool(self.access_restrictions - permissions_as_set)

    # todo: add overload stubs

    def __or__(self, other: AccessRestrictionsEval) -> AccessRestrictionsEval:
        if isinstance(other, AccessRestrictionsAllIDs):
            if other.access_restrictions <= self.access_restrictions:
                return other
            if self.access_restrictions <= other.access_restrictions:
                return self
            return AccessRestrictionsOr(children=frozenset((self, other)))
        return other | self

    def __and__[T: AccessRestrictionsEval](self, other: T) -> T:
        if isinstance(other, AccessRestrictionsAllIDs):
            if other.access_restrictions <= self.access_restrictions:
                return self
            if self.access_restrictions <= other.access_restrictions:
                return other
            return AccessRestrictionsAllIDs(self.access_restrictions | other.access_restrictions)

        return other & self

    def __sub__(self, other: frozenset[int]) -> Union[Self, NoAccessRestrictionsCls]:
        new_ids = self.access_restrictions - other
        if not new_ids:
            return NoAccessRestrictions
        if new_ids == self.access_restrictions:
            return self
        return AccessRestrictionsAllIDs(new_ids)

    @classmethod
    def build(cls, access_restrictions: Iterable[int | None]) -> Union[NoAccessRestrictionsCls, Self]:
        access_restrictions = frozenset(access_restrictions) - {None}
        if not access_restrictions:
            return NoAccessRestrictions
        return cls(access_restrictions)

    @property
    def relevant_permissions(self) -> frozenset[int]:
        return self.access_restrictions

    @property
    def minimum_permissions(self) -> frozenset[int]:
        return self.access_restrictions

    def simplify(self) -> Self:
        return self

    def flatten(self) -> frozenset[PermissionsAsSet]:
        return frozenset((self.access_restrictions, ))

    @classmethod
    def _validate(cls, value: Sequence[int] | Self) -> Self:
        if isinstance(value, AccessRestrictionsAllIDs):
            return value
        return cls(frozenset(value))

    @classmethod
    def _serialize(cls, value: Self) -> tuple[int, ...]:
        return tuple(value.access_restrictions)

    schema = core_schema.tuple_variable_schema(
        core_schema.int_schema(gt=0),
        min_length=1,
    )

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any=None, handler=None) -> CoreSchema:
        schema = core_schema.no_info_after_validator_function(
            cls._validate,
            core_schema.union_schema([core_schema.is_instance_schema(cls), cls.schema]),
            serialization=core_schema.plain_serializer_function_ser_schema(
                cls._serialize, info_arg=False, return_schema=cls.schema,
            ),
        )
        # confused? me too. it's needed because https://github.com/pydantic/pydantic/issues/7779
        cls.__pydantic_serializer__ = SchemaSerializer(schema)
        return schema


# todo: check that all access restrictions, even the ones from the location groups, actually go into the map renderer


@dataclass(frozen=True, slots=True)
class AccessRestrictionsOr(AccessRestrictionsEval):
    children: frozenset[AccessRestrictionsAllIDs]

    def can_see(self, permissions_as_set: PermissionsAsSet) -> bool:
        return any(child.can_see(permissions_as_set) for child in self.children)

    # todo: add overload stubs

    def __or__(self, other: AccessRestrictionsEval) -> AccessRestrictionsEval:
        if isinstance(other, AccessRestrictionsAllIDs):
            if not any((child.access_restrictions <= other.access_restrictions) for child in self.children):
                # todo: optimize / pull out stuff
                return AccessRestrictionsOr(self.children | {other})
            return self
        if isinstance(other, AccessRestrictionsOr):
            new_sets = tuple(
                other_child for other_child in other.children
                if not any((child.access_restrictions <= other_child.access_restrictions) for child in self.children)
            )
            # todo: optimize / pull out stuff
            if new_sets:
                return AccessRestrictionsOr(self.children | frozenset(new_sets))
            return self
        raise ValueError

    def __and__(self, other: AccessRestrictionsEval) -> AccessRestrictionsEval:
        if isinstance(other, AccessRestrictionsAllIDs):
            new_children = frozenset((child & other) for child in self.children)
            if len(new_children) == 1:
                return next(iter(new_children))
            return AccessRestrictionsOr(new_children)

        if isinstance(other, AccessRestrictionsOr):
            return AccessRestrictionsAnd(children=frozenset((self, other)))

        return other & self

    def __sub__(self, other: frozenset[int]) -> AccessRestrictionsEval:
        new_children = frozenset(new_child for new_child in ((child - other) for child in self.children)
                                 if isinstance(new_child, AccessRestrictionsAllIDs))
        if not new_children:
            return NoAccessRestrictions
        if len(new_children) == 1:
            return next(iter(new_children))
        return AccessRestrictionsOr(new_children)

    @classmethod
    def build(cls, children: Iterable[AccessRestrictionsEval]) -> AccessRestrictionsEval:
        return reduce(operator.or_, children, NoAccessRestrictions)

    @property
    def relevant_permissions(self) -> frozenset[int]:
        return reduce(operator.or_, (child.relevant_permissions for child in self.children), frozenset())

    @property
    def minimum_permissions(self) -> frozenset[int]:
        return reduce(operator.and_, (child.minimum_permissions for child in self.children))

    def simplify(self) -> Union[Self, "AccessRestrictionsAnd"]:
        minimum_permissions = self.minimum_permissions
        if not minimum_permissions:
            return self
        return AccessRestrictionsAnd(ids=AccessRestrictionsAllIDs(minimum_permissions),
                                     children=frozenset((self - minimum_permissions,)))

    def flatten(self) -> frozenset[PermissionsAsSet]:
        return frozenset(child.access_restrictions for child in self.children)

    @classmethod
    def _validate(cls, value: Sequence[Sequence[int]] | Self) -> Self:
        if isinstance(value, AccessRestrictionsOr):
            return value
        return cls(frozenset(AccessRestrictionsAllIDs._validate(subval) for subval in value))

    @classmethod
    def _serialize(cls, value: Self) -> tuple[tuple[int, ...], ...]:
        return tuple(AccessRestrictionsAllIDs._serialize(child) for child in value.children)

    schema = core_schema.tuple_variable_schema(
        AccessRestrictionsAllIDs.schema,
        min_length=2,
    )

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any = None, handler=None) -> CoreSchema:
        schema = core_schema.no_info_after_validator_function(
            cls._validate,
            core_schema.union_schema([core_schema.is_instance_schema(cls), cls.schema]),
            serialization=core_schema.plain_serializer_function_ser_schema(
                cls._serialize, info_arg=False, return_schema=cls.schema,
            ),
        )
        # confused? me too. it's needed because https://github.com/pydantic/pydantic/issues/7779
        cls.__pydantic_serializer__ = SchemaSerializer(schema)
        return schema


@dataclass(frozen=True, slots=True)
class AccessRestrictionsAnd(AccessRestrictionsEval):
    ids: Optional[AccessRestrictionsAllIDs] = None
    children: frozenset[AccessRestrictionsOr] = frozenset()

    def can_see(self, permissions_as_set: PermissionsAsSet) -> bool:
        return (
            (True if self.ids is None else self.ids.can_see(permissions_as_set))
            and all(child.can_see(permissions_as_set) for child in self.children)
        )

    # todo: add overload stubs

    def __or__(self, other: AccessRestrictionsEval) -> AccessRestrictionsEval:
        raise ValueError

    def __and__[T: AccessRestrictionsEval](self, other: T) -> T:
        match other:
            case AccessRestrictionsAllIDs():
                return AccessRestrictionsAnd(
                    ids=other if self.ids is None else (self.ids & other),
                    children=self.children,
                )
            case AccessRestrictionsOr():
                return AccessRestrictionsAnd(
                    ids=self.ids,
                    children=self.children | {other},
                )
            case AccessRestrictionsAnd():
                return AccessRestrictionsAnd(
                    ids=(other if self.ids is None else (self.ids if other.ids is None else (self.ids & other.ids))),
                    children=self.children | other.children,
                )
            case NoAccessRestrictionsCls():
                return other & self
            case _:
                raise ValueError

    def __sub__(self, other: frozenset[int]) -> AccessRestrictionsEval:
        new_ids = (self.ids or NoAccessRestrictions) - other
        new_children = deque()

        full_other = (
            other if isinstance(new_ids, NoAccessRestrictionsCls) else other | new_ids.access_restrictions
        )

        for or_child in self.children:
            new_or_child = or_child - full_other
            if isinstance(new_or_child, AccessRestrictionsOr):
                new_children.append(new_or_child)
            elif isinstance(new_or_child, AccessRestrictionsAllIDs):
                new_ids &= new_or_child

        new_children = frozenset(new_children)

        if not new_children:
            return new_ids

        if isinstance(new_ids, NoAccessRestrictionsCls):
            if not new_children:
                return NoAccessRestrictions
            if len(new_children) == 1:
                return next(iter(new_children))
            new_ids = None

        return AccessRestrictionsAnd(new_ids, new_children)

    @classmethod
    def build(cls, children: Iterable[AccessRestrictionsEval]) -> AccessRestrictionsEval:
        return reduce(operator.and_, children, NoAccessRestrictions)

    @property
    def relevant_permissions(self) -> frozenset[int]:
        return reduce(operator.or_, (child.relevant_permissions for child in self.children),
                      frozenset() if self.ids is None else self.ids.relevant_permissions)

    @property
    def minimum_permissions(self) -> frozenset[int]:
        return reduce(operator.or_, (child.minimum_permissions for child in self.children),
                      frozenset() if self.ids is None else self.ids.minimum_permissions)

    def simplify(self) -> Self:
        new_ids = self.ids or NoAccessRestrictions
        new_children = deque()
        for child in self.children:
            new_child = child.simplify()
            if isinstance(new_child, AccessRestrictionsAnd):
                new_ids &= new_child.ids
                new_children.extend(new_child.children)
            else:
                new_children.append(new_child)
        new_children = frozenset(new_children)
        if new_children == self.children:
            return self
        return AccessRestrictionsAnd(ids=None if isinstance(new_ids, NoAccessRestrictionsCls) else new_ids,
                                     children=new_children)

    def flatten(self) -> frozenset[PermissionsAsSet]:
        # todo: probably good to simplify/optimize some more here?
        min_ids = self.ids.access_restrictions if self.ids is not None else frozenset()
        return frozenset(
            reduce(operator.or_, choices, min_ids)
            for choices in product(*(child.flatten() for child in self.children))
        )

    @classmethod
    def _validate(cls, value) -> Self:
        if isinstance(value, AccessRestrictionsAnd):
            return value
        return cls(ids=None if value[0] is None else AccessRestrictionsAllIDs(frozenset(value[0])),
                   children=frozenset(AccessRestrictionsOr._validate(subval) for subval in value[1:]))

    @classmethod
    def _serialize(cls, value: Self) -> tuple[Optional[tuple[int, ...]], tuple[tuple[int, ...], ...], ...]:
        return (
            AccessRestrictionsAllIDs._serialize(value.ids) if value.ids else None,
            *(AccessRestrictionsOr._serialize(child) for child in value.children),
        )

    schema = core_schema.tuple_positional_schema(
        items_schema=[
            core_schema.union_schema([
                core_schema.none_schema(),
                AccessRestrictionsAllIDs.schema,
            ])
        ],
        extras_schema=AccessRestrictionsOr.schema,
    )

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any = None, handler=None) -> CoreSchema:
        schema = core_schema.no_info_after_validator_function(
            cls._validate,
            core_schema.union_schema([core_schema.is_instance_schema(cls), cls.schema]),
            serialization=core_schema.plain_serializer_function_ser_schema(
                cls._serialize, info_arg=False, return_schema=cls.schema,
            ),
        )
        # confused? me too. it's needed because https://github.com/pydantic/pydantic/issues/7779
        cls.__pydantic_serializer__ = SchemaSerializer(schema)
        return schema


AccessRestrictionsEvalSchema = Union[
    NoAccessRestrictionsCls,
    AccessRestrictionsAllIDs,
    AccessRestrictionsOr,
    AccessRestrictionsAnd,
]


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
    access_restrictions: set[int] = field(default_factory=set)
    spaces: dict[int, bool] = field(default_factory=dict)
    all_base_mapdata: bool = False
    view_sources: bool = False
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
        self._active: ContextVar[MapPermissions | None] = ContextVar("active_map_permission", default=None)

    def set_value(self, value: MapPermissions | None):
        self._active.set(value)

    def get_value(self) -> MapPermissions:
        value = self._active.get()
        if value is None:
            if not apps.ready:
                return ManualMapPermissions.get_full_access()

            # todo: this should fail, absolutely
            if 'manage.py' in sys.argv and 'runserver' not in sys.argv:
                warnings.warn('No map permission context set, defaulting to full context.', DeprecationWarning)
                return ManualMapPermissions.get_full_access()

            warnings.warn('No map permission context set, defaulting to public context.', DeprecationWarning)
            return ManualMapPermissions.get_public_access()
        return value

    @cached_property
    def disable_access_checks(self) -> FullAccessContextManager:
        return FullAccessContextManager(self)

    @contextmanager
    def override(self, value: MapPermissions):
        # Apparently asgiref.local cannot be trusted to actually keep the data local per-request?
        # See: https://github.com/django/asgiref/issues/473
        # This is why we use contextvars directly. However, still feeling paranoid. So lets double check for now.
        stack = traceback.format_stack()
        prev_value = self._active.get()
        token = self._active.set(value)
        try:
            yield
        finally:
            if self._active.get() != value:
                print(stack)
                raise ValueError(f'SOMETHING IS VERY WRONG (1), SECURITY ISSUE '
                                 f'got {self.get_value()}, expected {value}')

            self._active.reset(token)
            if self._active.get() != prev_value:
                print(stack)
                raise ValueError(f'SOMETHING IS VERY WRONG (2), SECURITY ISSUE '
                                 f'got {self.get_value()}, expected {prev_value}')

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
        return (
            compress_sorted_list_of_int(sorted(self.access_restrictions)).decode()
            + f":{self.view_sources:d}"  # todo: get rid of view_sources
        )

    @property
    def base_mapdata_cache_key(self) -> str:
        return 'a' if self.all_base_mapdata else (compress_sorted_list_of_int(sorted(self.spaces)).decode())


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
        if not self._has_minimum_permissions(permissions_as_set):
            return {}
        return {key: value for key, value in self._data.items()
                if value.effective_access_restrictions.can_see(permissions_as_set)}  # noqa

    @cached_property
    def _relevant_permissions(self) -> PermissionsAsSet:
        return reduce(operator.or_, (item.effective_access_restrictions.relevant_permissions  # noqa
                                     for item in self._data.values()),
                      frozenset((FullAccessTo.RESTRICTIONS, )))

    @cached_property
    def _minimum_permissions(self) -> tuple[PermissionsAsSet, ...]:
        """
        Possible minimum permissions to get any result.
        If the user doesn't have all of at least one of these, the result will be empty.
        """
        common_permissions: PermissionsAsSet = reduce(  # noqa
            operator.and_, (item.effective_access_restrictions.minimum_permissions  # noqa
                            for item in self._data.values())
        ) if self._data else frozenset()
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
        if not value.effective_access_restrictions.can_see(active_map_permissions.access_restrictions):
           raise KeyError(key)
        return value

    def get(self, key: KT, default=None):
        value = self._data.get(key, default)
        if value is not None and not value.effective_access_restrictions.can_see(active_map_permissions.as_set):
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


class BaseMapPermissionGuardedSet[T](BaseMapPermissionGuarded[frozenset[T]], ABC):
    """
    Base class for a wrapper that guards a sequence (output as a set) based on map permissions.
    """
    _data: Sequence[T]

    def __len__(self) -> int:
        return len(self._get())

    def __iter__(self) -> Iterator[T]:
        return iter(self._get())

    def __contains__(self, item) -> bool:
        return item in self._get()


class MapPermissionGuardedSequence[T: AccessRestrictionLogicMixin](BaseMapPermissionGuardedSequence[T]):
    """
    Wraps a sequence of AccessRestrictionLogicMixin objects.
    Acts like a sequence (like list, tuple, ...) but will filter objects based on the active map permissions.
    Caches the last 16 configurations.
    """
    def __init__(self, data: Sequence[T]):
        self._data = data

    def _get_for_permissions(self, permissions_as_set: PermissionsAsSet) -> tuple[T, ...]:
        if not self._has_minimum_permissions(permissions_as_set):
            return ()
        if FullAccessTo.RESTRICTIONS in permissions_as_set:
            return tuple(self._data)
        return tuple(item for item in self._data if item.effective_access_restrictions.can_see(permissions_as_set))

    @cached_property
    def _relevant_permissions(self) -> PermissionsAsSet:
        return reduce(operator.or_, (item.effective_access_restrictions.relevant_permissions
                                     for item in self._data), frozenset())

    @cached_property
    def _minimum_permissions(self) -> tuple[PermissionsAsSet, ...]:
        common_permissions: PermissionsAsSet = reduce(
            operator.and_, (item.effective_access_restrictions.minimum_permissions for item in self._data)
        ) if self._data else frozenset()
        if not common_permissions:
            return ()
        return (
            frozenset((FullAccessTo.RESTRICTIONS,)),
            common_permissions,
        )

    def __repr__(self):
        return f"MapPermissionGuardedSequence({self._data})"


class MapPermissionTaggedItem[T](NamedTuple):
    """
    Tags a value with access permissions
    """
    value: T
    access_restrictions: AccessRestrictionsEvalSchema

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
            if any((item.access_restrictions <= d) for d in done):
                # skip restriction supersets of other instances of the same value
                continue
            done.append(item.access_restrictions)
            yield item

    @staticmethod
    def skip_redundant_keep_order[T](values: Iterable["MapPermissionTaggedItem[T]"]) -> Generator["MapPermissionTaggedItem[T]"]:
        """
        Yield every item unless it there was already an item with the same value that had a subset of access restrictions.
        """
        # todo: better name
        done_restrictions_for_values: dict[T, set[AccessRestrictionsEval]] = defaultdict(set)
        for item in values:
            if any((item.access_restrictions <= done.access_restrictions)
                   for done in done_restrictions_for_values[item.value]):
                continue
            yield item

    @staticmethod
    def skip_redundant[T](values: Iterable["MapPermissionTaggedItem[T]"],
                          *, reverse: bool = False) -> Generator["MapPermissionTaggedItem[T]"]:
        """
        Sort items by value – ascending by default, descending if reverse=True
        Then, yield all items that unless there is one with the same value and a subset of access restrictions.
        """
        # todo: is this fine?
        values = sorted(values, key=lambda item: (item.value * (-1 if reverse else 1),
                                                  len(item.access_restrictions.relevant_permissions)))
        yield from MapPermissionTaggedItem.skip_redundant_presorted(values)

    @staticmethod
    def add_restrictions_and_skip_redundant[T](
            values: Iterable["MapPermissionTaggedItem[T]"],
            access_restrictions: AccessRestrictionsEval) -> Generator["MapPermissionTaggedItem[T]"]:
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
        if not self._has_minimum_permissions(permissions_as_set):
            return ()
        if FullAccessTo.RESTRICTIONS in permissions_as_set:
            return tuple(item.value for item in self._data)
        return tuple(item.value for item in self._data if item.access_restrictions.can_see(permissions_as_set))

    @cached_property
    def _relevant_permissions(self) -> PermissionsAsSet:
        return reduce(operator.or_, (item.access_restrictions.relevant_permissions for item in self._data),
                      frozenset((FullAccessTo.RESTRICTIONS, )))

    @cached_property
    def _minimum_permissions(self) -> tuple[PermissionsAsSet, ...]:
        common_permissions: PermissionsAsSet = reduce(  # noqa
            operator.and_, (item.access_restrictions.minimum_permissions for item in self._data),
        ) if self._data else frozenset()
        if not common_permissions:
            return ()
        return (
            frozenset((FullAccessTo.RESTRICTIONS,)),
            common_permissions,
        )

    def __repr__(self):
        return f"MapPermissionGuardedTaggedSequence({self._data})"


class MapPermissionGuardedTaggedUniqueSequence[T](BaseMapPermissionGuardedSequence[T]):
    """
    Wraps a sequence of MapPermissionTaggedItem[T] objects.
    Acts like a Sequence[T] (like list, tuple, ...) but will filter objects based on the active map permissions.
    Additionally, duplicates are omitted.
    Caches the last 16 configurations.
    """
    def __init__(self, data: Sequence[MapPermissionTaggedItem[T]]):
        self._data = data

    def _get_for_permissions(self, permissions_as_set: PermissionsAsSet) -> tuple[T, ...]:
        if not self._has_minimum_permissions(permissions_as_set):
            return ()
        if FullAccessTo.RESTRICTIONS in permissions_as_set:
            return tuple({item.value: None for item in self._data})
        return tuple({item.value: None for item in self._data if item.access_restrictions.can_see(permissions_as_set)})

    # todo: this is duplicate code
    @cached_property
    def _relevant_permissions(self) -> PermissionsAsSet:
        return reduce(operator.or_, (item.access_restrictions.relevant_permissions for item in self._data),
                      frozenset((FullAccessTo.RESTRICTIONS, )))

    @cached_property
    def _minimum_permissions(self) -> tuple[PermissionsAsSet, ...]:
        common_permissions: PermissionsAsSet = reduce(  # noqa
            operator.and_, (item.access_restrictions.minimum_permissions for item in self._data),
        ) if self._data else frozenset()
        if not common_permissions:
            return ()
        return (
            frozenset((FullAccessTo.RESTRICTIONS,)),
            common_permissions,
        )

    def __repr__(self):
        return f"MapPermissionGuardedTaggedSet({self._data})"


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
        if not self._has_minimum_permissions(permissions_as_set):
            return self._default
        try:
            if FullAccessTo.RESTRICTIONS in permissions_as_set:
                return next(iter(item.value for item in self._data))
            return next(iter(item.value for item in self._data if item.access_restrictions.can_see(permissions_as_set)))
        except StopIteration:
            return self._default

    @cached_property
    def _relevant_permissions(self) -> PermissionsAsSet:
        """ All permissions that may affect the result here. """
        return reduce(operator.or_, (item.access_restrictions.relevant_permissions for item in self._data),
                      frozenset((FullAccessTo.RESTRICTIONS, )))

    @cached_property
    def _minimum_permissions(self) -> tuple[PermissionsAsSet, ...]:
        common_permissions: PermissionsAsSet = reduce(  # noqa
            operator.and_, (item.access_restrictions.minimum_permissions for item in self._data)
        ) if self._data else frozenset()
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
        return f"MapPermissionGuardedTaggedValue({self._data}, default={self._default})"


class MapPermissionMaskedTaggedValue[T, MT = T](BaseMapPermissionGuardedValue[T | MT]):
    """
    Wraps two BaseMapPermissionGuardedValue instances, 
    deliver them the private or masked one based on the user's space permissions.
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
            return f"MapPermissionMaskedValue({self._value})"
        else:
            return (f"MapPermissionMaskedValue({self._value}, masked_value={self._value}, space_id={self._space_id})")


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
            operator.and_, (item._minimum_permissions for item in self._data)
        ) if self._data else frozenset()
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
