import re
import struct
import typing
from abc import ABC, abstractmethod
from collections import namedtuple
from contextlib import suppress
from dataclasses import dataclass
from dataclasses import fields as dataclass_fields
from enum import IntEnum
from typing import Any, Sequence

from annotated_types import SLOTS, BaseMetadata, Ge
from pydantic.fields import Field, FieldInfo
from pydantic_extra_types.mac_address import MacAddress

from c3nav.api.utils import NonEmptyStr, TwoNibblesEncodable
from c3nav.mesh.utils import indent_c


@dataclass(frozen=True, **SLOTS)
class VarLen(BaseMetadata):
    var_len_name: NonEmptyStr = "num"


@dataclass(frozen=True, **SLOTS)
class NoDef(BaseMetadata):
    no_def: bool = True


@dataclass(frozen=True, **SLOTS)
class AsHex(BaseMetadata):
    as_hex: bool = True


@dataclass(frozen=True, **SLOTS)
class LenBytes(BaseMetadata):
    len_bytes: typing.Annotated[int, Ge(1)]


@dataclass(frozen=True, **SLOTS)
class AsDefinition(BaseMetadata):
    as_definition: bool = True


@dataclass(frozen=True, **SLOTS)
class CEmbed(BaseMetadata):
    c_embed: bool = True


@dataclass(frozen=True, **SLOTS)
class CName(BaseMetadata):
    c_name: NonEmptyStr


@dataclass(frozen=True, **SLOTS)
class CDoc(BaseMetadata):
    c_doc: NonEmptyStr


@dataclass
class ExistingCStruct():
    name: NonEmptyStr
    includes: list[str]


def discriminator_value(**kwargs):
    return type('DiscriminatorValue', (), {
        **{name: value for name, value in kwargs.items()},
        '__annotations__': {
            name: typing.Annotated[typing.Literal[value], Field(init=False)]
            for name, value in kwargs.items()
        }
    })


class BaseFormat(ABC):

    def get_var_num(self):
        return 0

    @abstractmethod
    def encode(self, value):
        pass

    @classmethod
    @abstractmethod
    def decode(cls, data) -> tuple[Any, bytes]:
        pass

    @abstractmethod
    def get_min_size(self):
        pass

    @abstractmethod
    def get_max_size(self):
        pass

    def get_size(self, calculate_max=False):
        if calculate_max:
            return self.get_max_size()
        else:
            return self.get_min_size()

    @abstractmethod
    def get_c_parts(self) -> tuple[str, str]:
        pass

    def get_c_code(self, name) -> str:
        pre, post = self.get_c_parts()
        return "%s %s%s;" % (pre, name, post)

    def get_c_definitions(self) -> dict[str, str]:
        return {}

    def get_typedef_name(self):
        raise TypeError('no typedef for %r' % self)

    def get_c_includes(self) -> set:
        return set()


def get_int_type(min_: int, max_: int) -> str | None:
    if min_ < 0:
        if min_ < -(2 ** 63) or max_ > 2 ** 63 - 1:
            return None
        elif min_ < -(2 ** 31) or max_ > 2 ** 31 - 1:
            return "q"
        elif min_ < -(2 ** 15) or max_ > 2 ** 15 - 1:
            return "i"
        elif min_ < -(2 ** 7) or max_ > 2 ** 7 - 1:
            return "h"
        else:
            return "b"

    if max_ > 2 ** 64 - 1:
        return None
    elif max_ > 2 ** 32 - 1:
        return "Q"
    elif max_ > 2 ** 16 - 1:
        return "I"
    elif max_ > 2 ** 8 - 1:
        return "H"
    else:
        return "B"


class SimpleFormat(BaseFormat):
    def __init__(self, fmt):
        self.fmt = fmt
        self.size = struct.calcsize(fmt)

        self.c_type = self.c_types[self.fmt[-1]]
        self.num = int(self.fmt[:-1]) if len(self.fmt) > 1 else 1

    def encode(self, value):
        if self.num == 1:
            return struct.pack(self.fmt, value)
        return struct.pack(self.fmt, *value)

    def decode(self, data: bytes) -> tuple[Any, bytes]:
        value = struct.unpack(self.fmt, data[:self.size])
        if len(value) == 1:
            value = value[0]
        return value, data[self.size:]

    def get_min_size(self):
        return self.size

    def get_max_size(self):
        return self.size

    c_types = {
        "B": "uint8_t",
        "H": "uint16_t",
        "I": "uint32_t",
        "Q": "uint64_t",
        "b": "int8_t",
        "h": "int16_t",
        "i": "int32_t",
        "q": "int64_t",
        "s": "char",
    }

    def get_c_parts(self):
        return self.c_type, ("" if self.num == 1 else ("[%d]" % self.num))


class SimpleConstFormat(SimpleFormat):
    def __init__(self, fmt, const_value: int):
        super().__init__(fmt)
        self.const_value = const_value

    def decode(self, data: bytes) -> tuple[Any, bytes]:
        value, out_data = super().decode(data)
        if value != self.const_value:
            raise ValueError('const_value is wrong')
        return value, out_data


class EnumFormat(SimpleFormat):
    def __init__(self, enum_cls: typing.Type[IntEnum], fmt="B", *, as_hex=False, c_definition=True):
        super().__init__(fmt)
        self.enum_cls = enum_cls
        self.as_hex = as_hex
        self.c_definition = c_definition

        self.c_struct_name = normalize_name(enum_cls.__name__) + '_t'

    def decode(self, data: bytes) -> tuple[Any, bytes]:
        value, out_data = super().decode(data)
        return self.enum_cls(value), out_data

    def get_typedef_name(self):
        return '%s_t' % normalize_name(self.enum_cls.__name__)

    def get_c_parts(self):
        if not self.c_definition:
            return super().get_c_parts()
        return self.c_struct_name, ""

    def get_c_definitions(self) -> dict[str, str]:
        if not self.c_definition:
            return {}
        prefix = normalize_name(self.enum_cls.__name__).upper()
        options = []
        last_value = None
        for item in self.enum_cls:
            if last_value is not None and item.value != last_value + 1:
                options.append('')
            last_value = item.value
            options.append("%(prefix)s_%(name)s = %(value)s," % {
                "prefix": prefix,
                "name": normalize_name(item.name).upper(),
                "value": ("0x%02x" if self.as_hex else "%d") % item.value
            })

        return {
            self.c_struct_name: "enum {\n%(options)s\n};\ntypedef uint8_t %(name)s;" % {
                "options": indent_c("\n".join(options)),
                "name": self.c_struct_name,
            }
        }


class TwoNibblesEnumFormat(SimpleFormat):
    def __init__(self, data_cls):
        self.data_cls = data_cls
        super().__init__('B')

    def decode(self, data: bytes) -> tuple[bool, bytes]:
        fields = dataclass_fields(self.data_cls)
        value, data = super().decode(data)
        return self.data_cls(fields[0].type(value // 2 ** 4), fields[1].type(value // 2 ** 4)), data

    def encode(self, value):
        fields = dataclass_fields(self.data_cls)
        return super().encode(
            getattr(value, fields[0].name).value * 2 ** 4 +
            getattr(value, fields[1].name).value * 2 ** 4
        )


class BoolFormat(SimpleFormat):
    def __init__(self):
        super().__init__('B')

    def encode(self, value):
        return super().encode(int(value))

    def decode(self, data: bytes) -> tuple[bool, bytes]:
        value, data = super().decode(data)
        if value > 1:
            raise ValueError('Boolean value > 1')
        return bool(value), data


class FixedStrFormat(SimpleFormat):
    def __init__(self, num):
        self.num = num
        super().__init__('%ds' % self.num)

    def encode(self, value: str):
        return value.encode()[:self.num].ljust(self.num, bytes((0,))),

    def decode(self, data: bytes) -> tuple[str, bytes]:
        return data[:self.num].rstrip(bytes((0,))).decode(), data[self.num:]


class FixedBytesFormat(SimpleFormat):
    def __init__(self, num):
        self.num = num
        super().__init__('%dB' % self.num)

    def encode(self, value: str):
        return super().encode(tuple(value))

    def decode(self, data: bytes) -> tuple[bytes, bytes]:
        return data[:self.num], data[self.num:]


class FixedHexFormat(SimpleFormat):
    def __init__(self, num, sep=''):
        self.num = num
        self.sep = sep
        super().__init__('%dB' % self.num)

    def encode(self, value: str):
        return super().encode(tuple(bytes.fromhex(value.replace(':', ''))))

    def decode(self, data: bytes) -> tuple[str, bytes]:
        return self.sep.join(('%02x' % i) for i in data[:self.num]), data[self.num:]


class BaseVarFormat(BaseFormat, ABC):
    def __init__(self, max_num):
        self.num_fmt = 'H'
        self.num_size = struct.calcsize(self.num_fmt)
        self.max_num = max_num

    def get_min_size(self):
        return self.num_size

    def get_max_size(self):
        return self.num_size + self.max_num * self.get_var_num()

    def get_num_c_code(self):
        return SimpleFormat(self.num_fmt).get_c_code("num")


class VarArrayFormat(BaseVarFormat):
    def __init__(self, child_type, max_num):
        super().__init__(max_num=max_num)
        self.child_type = child_type
        self.child_size = self.child_type.get_min_size()

    def get_var_num(self):
        return self.child_size
        pass

    def encode(self, values: Sequence) -> bytes:
        num = len(values)
        if num > self.max_num:
            raise ValueError(f'too many elements, got {num} but maximum is {self.max_num}')
        data = struct.pack(self.num_fmt, num)
        for value in values:
            data += self.child_type.encode(value)
        return data

    def decode(self, data: bytes) -> tuple[list[Any], bytes]:
        num = struct.unpack(self.num_fmt, data[:self.num_size])[0]
        if num > self.max_num:
            raise ValueError(f'too many elements, got {num} but maximum is {self.max_num}')
        data = data[self.num_size:]
        result = []
        for i in range(num):
            item, data = self.child_type.decode(data)
            result.append(item)
        return result, data

    def get_c_parts(self):
        pre, post = self.child_type.get_c_parts()
        return super().get_num_c_code() + "\n" + pre, "[0]" + post


class VarStrFormat(BaseVarFormat):
    def __init__(self, max_len):
        super().__init__(max_num=max_len)

    def get_var_num(self):
        return 1

    def encode(self, value: str) -> bytes:
        num = len(value)
        if num > self.max_num:
            raise ValueError(f'too many elements, got {num} but maximum is {self.max_num}')
        return struct.pack(self.num_fmt, num) + value.encode()

    def decode(self, data: bytes) -> tuple[str, bytes]:
        num = struct.unpack(self.num_fmt, data[:self.num_size])[0]
        if num > self.max_num:
            raise ValueError(f'too many elements, got {num} but maximum is {self.max_num}')
        return data[self.num_size:self.num_size + num].rstrip(bytes((0,))).decode(), data[self.num_size + num:]

    def get_c_parts(self):
        return super().get_num_c_code() + "\n" + "char", "[0]"


class VarBytesFormat(BaseVarFormat):
    def __init__(self, max_size):
        super().__init__(max_num=max_size)

    def get_var_num(self):
        return 1

    def encode(self, value: bytes) -> bytes:
        num = len(value)
        if num > self.max_num:
            raise ValueError(f'too many elements, got {num} but maximum is {self.max_num}')
        return struct.pack(self.num_fmt, num) + value

    def decode(self, data: bytes) -> tuple[bytes, bytes]:
        num = struct.unpack(self.num_fmt, data[:self.num_size])[0]
        if num > self.max_num:
            raise ValueError(f'too many elements, got {num} but maximum is {self.max_num}')
        return data[self.num_size:self.num_size + num].rstrip(bytes((0,))), data[self.num_size + num:]

    def get_c_parts(self):
        return super().get_num_c_code() + "\n" + "uint8_t", "[0]"


T = typing.TypeVar('T')


class StructFormat(BaseFormat):
    _format_cache: dict[typing.Type, dict[str, BaseFormat]]

    def __new__(cls, model: typing.Type[T]):
        result = cls._format_cache.get(model, None)
        if not result:
            result = super().__new__(model)
            cls._format_cache.get(model, result)
        return result

    def __init__(self, model: typing.Type[T]):
        self.model = model

        self._field_formats = {}
        self._as_definition = set()
        self._c_embed = set()
        self._c_names = {}
        self._c_docs = {}
        self._no_init_data = set()
        for name, type_hint in typing.get_type_hints(self.model, include_extras=True).items():
            if type_hint is typing.ClassVar:
                continue  # todo: nicer?
            type_hint = split_type_hint(type_hint)

            if any(getattr(m, "as_definition", False) for m in type_hint.metadata):
                self._as_definition.add(name)
            if any(getattr(m, "c_embed", False) for m in type_hint.metadata):
                self._c_embed.add(name)
            if not all(getattr(m, "init", True) for m in type_hint.metadata):
                self._no_init_data.add(name)
            for m in type_hint.metadata:
                with suppress(AttributeError):
                    self._c_names[name] = m.c_name
                with suppress(AttributeError):
                    self._c_docs[name] = m.c_doc

            self._field_formats[name] = get_type_hint_format(type_hint, attr_name=name)

    def get_var_num(self):
        return sum([field_format.get_var_num() for name, field_format in self._field_formats.items()], start=0)

    def encode(self, instance: T, ignore_fields=()) -> bytes:
        data = bytes()
        for name, field_format in self._field_formats.items():
            if name in ignore_fields:
                continue
            data += field_format.encode(getattr(instance, name))
        return data

    def decode(self, data: bytes) -> tuple[T, bytes]:
        kwargs = {}
        for name, field_format in self._field_formats.items():
            value, data = field_format.decode(data)
            if name not in self._no_init_data:
                kwargs[name] = value
        return self.model(**kwargs), data

    def get_min_size(self) -> int:
        return sum((
            field_format.get_min_size() for field_format in self._field_formats.values()
        ), start=0)

    def get_max_size(self) -> int:
        raise ValueError

    def get_size(self, calculate_max=False):
        return sum((
            field_format.get_size(calculate_max=calculate_max) for field_format in self._field_formats.values()
        ), start=0)

    def get_c_struct_items(self, ignore_fields=None, no_empty=False, top_level=False):
        ignore_fields = set() if not ignore_fields else set(ignore_fields)

        items = []

        for name, field_format in self._field_formats.items():
            if name in ignore_fields:
                continue

            c_name = self._c_names.get(name, name)
            if not isinstance(field_format, (StructFormat, UnionFormat)):
                items.append((
                    (
                        ("%(typedef_name)s %(name)s;" % {
                            "typedef_name": field_format.get_typedef_name(),
                            "name": c_name,
                        })
                        if name in self._as_definition
                        else field_format.get_c_code(c_name)
                    ),
                    self._c_docs.get(name, None),
                )),
            else:
                if name in self._c_embed:
                    embedded_items = field_format.get_c_struct_items(ignore_fields, no_empty, top_level)
                    items.extend(embedded_items)
                else:
                    items.append((
                        (
                            ("%(typedef_name)s %(name)s;" % {
                                "typedef_name": field_format.get_typedef_name(),
                                "name": c_name,
                            })
                            if name in self._as_definition
                            else field_format.get_c_code(c_name, typedef=False)
                        ),
                        self._c_docs.get(name, None),
                    ))

        return items

    def get_c_parts(self, ignore_fields=None, no_empty=False, top_level=False) -> tuple[str, str]:
        # todo: parameters needed?
        with suppress(AttributeError):
            return (self.model.existing_c_struct.name, "")

        ignore_fields = set() if not ignore_fields else set(ignore_fields)

        pre = ""

        items = self.get_c_struct_items(ignore_fields=ignore_fields,
                                        no_empty=no_empty,
                                        top_level=top_level)

        if no_empty and not items:
            return "", ""

        # todo: struct comment
        if top_level:
            comment = self.model.__doc__.strip()
            if comment:
                pre += "/** %s */\n" % comment
            pre += "typedef struct __packed "
        else:
            pre += "struct __packed "

        pre += "{\n%(elements)s\n}" % {
            "elements": indent_c(
                "\n".join(
                    code + ("" if not comment else (" /** %s */" % comment))
                    for code, comment in items
                )
            ),
        }
        return pre, ""

    def get_c_code(self, name=None, ignore_fields=None, no_empty=False, typedef=True) -> str:
        pre, post = self.get_c_parts(ignore_fields=ignore_fields,
                                     no_empty=no_empty,
                                     top_level=typedef)
        if no_empty and not pre and not post:
            return ""
        return "%s %s%s;" % (pre, name, post)

    def get_c_definitions(self) -> dict[str, str]:
        definitions = {}
        for name, field_format in self._field_formats.items():
            definitions.update(field_format.get_c_definitions())
            if name in self._as_definition:
                typedef_name = field_format.get_typedef_name()
                if not isinstance(field_format, StructFormat):
                    definitions[typedef_name] = 'typedef %(code)s %(name)s;' % {
                        "code": ''.join(field_format.get_c_parts()),
                        "name": typedef_name,
                    }
                else:
                    definitions[typedef_name] = field_format.get_c_code(name=typedef_name, typedef=True)
        return definitions

    def get_typedef_name(self):
        return "%s_t" % normalize_name(self.model.__name__)

    def get_c_includes(self) -> set:
        result = set()
        with suppress(AttributeError):
            result.update(self.model.existing_c_struct.includes)
        for field_format in self._field_formats.values():
            result.update(field_format.get_c_includes())
        return result


class UnionFormat(BaseFormat):
    def __init__(self, model_formats: Sequence[StructFormat], discriminator: str, discriminator_as_hex: bool = False):
        self.discriminator = discriminator
        self.models = {
            getattr(model_format.model, discriminator): model_format for model_format in model_formats
        }
        if len(self.models) != len(model_formats):
            raise ValueError
        types = set(type(value) for value in self.models.keys())
        if len(types) != 1:
            raise ValueError
        type_ = tuple(types)[0]
        if not issubclass(type_, IntEnum):
            raise ValueError
        if discriminator_as_hex:
            # todo: nicer?
            type_ = typing.Annotated[type_, AsHex()]
        self.discriminator_format = get_type_hint_format(split_type_hint(type_))

    def get_var_num(self):
        return 0  # todo: is this always correct?

    def encode(self, instance) -> bytes:
        # todo: make sure instance is valid
        discriminator_value = getattr(instance, self.discriminator)
        self.discriminator_format.encode(discriminator_value)
        return self.models[discriminator_value].encode(instance, ignore_fields=(self.discriminator, ))

    def decode(self, data: bytes) -> tuple[T, bytes]:
        discriminator_value, remaining_data = self.discriminator_format.decode(data)
        return self.models[discriminator_value].decode(data)

    def get_min_size(self) -> int:
        return max([0] + [
            model_format.get_min_size()
            for model_format in self.models.values()
        ])

    def get_max_size(self) -> int:
        raise ValueError

    def get_size(self=False, calculate_max=False):
        return max([0] + [
            field_format.get_size(calculate_max=calculate_max)
            for field_format in self.models.values()
        ])

    def get_c_struct_items(self, ignore_fields=None, no_empty=False, top_level=False):
        return [
            (self.discriminator_format.get_c_code(self.discriminator), None),
            ("union __packed %s;" % self.get_c_union_code(ignore_fields), None),
        ]

    def get_c_union_size(self):
        return max(
            (model_format.get_min_size() for model_format in self.models.values()),
            default=0,
        ) - self.discriminator_format.get_min_size()

    def get_c_union_code(self, ignore_fields=None):
        union_items = []
        for key, model_format in self.models.items():
            base_name = normalize_name(getattr(key, 'name', model_format.model.__name__))  # todo: better?
            item_c_code = model_format.get_c_code(
                base_name, ignore_fields=(self.discriminator, ), typedef=False, no_empty=True
            )
            if item_c_code:
                union_items.append(item_c_code)
        size = self.get_c_union_size()
        union_items.append(
            "uint8_t bytes[%0d];" % size
        )
        return "{\n" + indent_c("\n".join(union_items)) + "\n}"

    def get_c_parts(self, ignore_fields=None, no_empty=False, top_level=False) -> tuple[str, str]:
        # todo: parameters needed?
        ignore_fields = set() if not ignore_fields else set(ignore_fields)

        pre = ""

        # todo: we should be able to shorten this considerably

        items = self.get_c_struct_items(ignore_fields=ignore_fields,
                                        no_empty=no_empty,
                                        top_level=top_level)

        if no_empty and not items:
            return "", ""

        if top_level:
            pre += "typedef struct __packed "
        else:
            pre += "struct __packed "

        pre += "{\n%(elements)s\n}" % {
            "elements": indent_c(
                "\n".join(
                    code + ("" if not comment else (" /** %s */" % comment))
                    for code, comment in items
                )
            ),
        }
        return pre, ""

    def get_c_code(self, name=None, ignore_fields=None, no_empty=False, typedef=True,) -> str:
        pre, post = self.get_c_parts(ignore_fields=ignore_fields,
                                     no_empty=no_empty,
                                     top_level=typedef)
        if no_empty and not pre and not post:
            return ""
        return "%s %s%s;" % (pre, name, post)

    def get_c_definitions(self) -> dict[str, str]:
        definitions = {}
        definitions.update(self.discriminator_format.get_c_definitions())
        for model_format in self.models.values():
            definitions.update(model_format.get_c_definitions())
        return definitions

    def get_typedef_name(self):
        names = [model_format.model.__name__ for model_format in self.models.values()]
        min_len = min(len(name) for name in names)
        longest_prefix = ''
        longest_suffix = ''
        for i in reversed(range(min_len)):
            a = set(name[:i] for name in names)
            if len(a) == 1:
                longest_prefix = tuple(a)[0]
                break
        for i in reversed(range(min_len)):
            a = set(name[-i:] for name in names)
            if len(a) == 1:
                longest_suffix = tuple(a)[0]
                break
        return "%s_t" % normalize_name(longest_prefix if len(longest_prefix) > len(longest_suffix) else longest_suffix)

    def get_c_includes(self) -> set:
        result = set()
        result.update(self.discriminator_format.get_c_includes())
        for model_format in self.models.values():
            result.update(model_format.get_c_includes())
        return result


SplitTypeHint = namedtuple("SplitTypeHint", ("base", "metadata"))


def split_type_hint(type_hint) -> SplitTypeHint:
    if typing.get_origin(type_hint) is typing.Annotated:
        field_infos = tuple(m for m in type_hint.__metadata__ if isinstance(m, FieldInfo))
        return SplitTypeHint(
            base=typing.get_args(type_hint)[0],
            metadata=(
                *(m for m in type_hint.__metadata__ if not isinstance(m, FieldInfo)),
                *(tuple(field_infos[0].metadata) if field_infos else ())
            )
        )

    if isinstance(type_hint, FieldInfo):
        return SplitTypeHint(
            base=type_hint.annotation,
            metadata=tuple(type_hint.metadata)
        )

    return SplitTypeHint(
        base=type_hint,
        metadata=()
    )


def get_format(type_, attr_name=None) -> BaseFormat:
    # todo: move this somewhere?
    return get_type_hint_format(split_type_hint(type_))


# todo: move this somewhere?
def get_type_hint_format(type_hint: SplitTypeHint, attr_name=None) -> BaseFormat:
    # todo: attr_name nicer?
    orig_type_base = type_hint.base

    outer_type_hint = None
    if typing.get_origin(type_hint.base) is list:
        outer_type_hint = SplitTypeHint(
            base=list,
            metadata=type_hint.metadata
        )
        type_hint = SplitTypeHint(
            base=typing.get_args(type_hint.base)[0],
            metadata=()
        )
        if typing.get_origin(type_hint.base) is typing.Annotated:
            type_hint = SplitTypeHint(
                base=typing.get_args(type_hint.base)[0],
                metadata=tuple(type_hint.base.__metadata__)
            )

    field_format = None

    if typing.get_origin(type_hint.base) is typing.Literal:
        literal_val = typing.get_args(type_hint.base)[0]
        if not isinstance(literal_val, int):
            raise ValueError()
        int_type = get_int_type(literal_val, literal_val)
        if int_type is None:
            raise ValueError('invalid range:', attr_name)
        field_format = SimpleConstFormat(int_type, const_value=literal_val)
    elif typing.get_origin(type_hint.base) is typing.Union:
        discriminator = None
        for m in type_hint.metadata:
            discriminator = getattr(m, 'discriminator', discriminator)
        if discriminator is None:
            raise ValueError('no discriminator')
        discriminator_as_hex = any(getattr(m, "as_hex", False) for m in type_hint.metadata)
        field_format = UnionFormat(
            model_formats=[StructFormat(type_) for type_ in typing.get_args(type_hint.base)],
            discriminator=discriminator,
            discriminator_as_hex=discriminator_as_hex,
        )
    elif type_hint.base is int:
        int_type = get_int_type(*get_int_min_max(type_hint))
        if int_type is None:
            raise ValueError('invalid range:', attr_name)
        field_format = SimpleFormat(int_type)
    elif type_hint.base is bool:
        field_format = BoolFormat()
    elif type_hint.base in (str, bytes):
        max_length = None
        var_len_name = None
        as_hex = False
        for m in type_hint.metadata:
            as_hex = getattr(m, 'as_hex', as_hex)

            ml = getattr(m, 'max_length', None)
            if ml is not None:
                max_length = ml if max_length is None else min(max_length, ml)

            vl = getattr(m, 'var_len_name', None)
            if vl is not None:
                if var_len_name is not None:
                    raise ValueError('can\'t set variable length name twice')
                var_len_name = vl
        if max_length is None:
            raise ValueError('missing str max_length:', attr_name)

        if type_hint.base is str:
            if var_len_name is not None:
                field_format = VarStrFormat(max_len=max_length)
            else:
                field_format = FixedHexFormat(max_length) if as_hex else FixedStrFormat(max_length)
        else:
            if var_len_name is None:
                field_format = FixedBytesFormat(num=max_length)
            else:
                field_format = VarBytesFormat(max_size=max_length)
    elif type_hint.base is MacAddress:
        from c3nav.mesh.dataformats import MacAddressFormat
        field_format = MacAddressFormat()
    elif isinstance(type_hint.base, type) and issubclass(type_hint.base, IntEnum):
        no_def = False
        as_hex = False
        len_bytes = None
        for m in type_hint.metadata:
            no_def = getattr(m, 'no_def', no_def)
            as_hex = getattr(m, 'as_hex', as_hex)
            len_bytes = getattr(m, 'len_bytes', len_bytes)

        if len_bytes:
            int_type = get_int_type(0, 2**(8*len_bytes-1))
        else:
            int_type = get_int_type(min(type_hint.base), max(type_hint.base))
            if int_type is None:
                raise ValueError('invalid range:', attr_name)
        field_format = EnumFormat(fmt=int_type, as_hex=as_hex, c_definition=not no_def)
    elif isinstance(type_hint.base, type) and issubclass(type_hint.base, TwoNibblesEncodable):
        field_format = TwoNibblesEnumFormat()
    elif isinstance(type_hint.base, type) and typing.get_type_hints(type_hint.base):
        field_format = StructFormat(model=type_hint.base)

    if field_format is None:
        raise ValueError('Unknown type annotation for c structs', type_hint.base)
    else:
        if outer_type_hint is not None and outer_type_hint.base is list:
            max_length = None
            var_len_name = None
            for m in outer_type_hint.metadata:
                ml = getattr(m, 'max_length', None)
                if ml is not None:
                    max_length = ml if max_length is None else min(max_length, ml)

                vl = getattr(m, 'var_len_name', None)
                if vl is not None:
                    if var_len_name is not None:
                        raise ValueError('can\'t set variable length name twice')
                    var_len_name = vl
            if max_length is None:
                raise ValueError('missing list max_length:', attr_name)
            if var_len_name:
                field_format = VarArrayFormat(field_format, max_num=max_length)
            else:
                raise ValueError('fixed-len list not implemented:', attr_name)

    return field_format


def get_int_min_max(type_hint):
    min_ = -(2 ** 63)
    max_ = 2 ** 63 - 1
    for m in type_hint.metadata:
        gt = getattr(m, 'gt', None)
        if gt is not None:
            min_ = max(min_, gt + 1)
        ge = getattr(m, 'ge', None)
        if ge is not None:
            min_ = max(min_, ge)
        lt = getattr(m, 'lt', None)
        if lt is not None:
            max_ = min(max_, lt - 1)
        le = getattr(m, 'le', None)
        if le is not None:
            max_ = min(max_, le)
    return max_, min_


def normalize_name(name):
    if '_' in name:
        name = name.lower()
    else:
        name = re.sub(
            r"(([a-z])([A-Z]))|(([a-zA-Z])([A-Z][a-z]))",
            r"\2\5_\3\6",
            name
        ).lower()

    name = re.sub(
        r"(ota)([a-z])",
        r"\1_\2",
        name
    ).lower()

    name = name.replace('config', 'cfg')
    name = name.replace('position', 'pos')
    name = name.replace('mesh_', '')
    name = name.replace('firmware', 'fw')
    name = name.replace('hardware', 'hw')
    return name
