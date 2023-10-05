import re
import struct
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, fields
from enum import IntEnum, unique, Enum
from typing import Self, Sequence, Any

from c3nav.mesh.utils import indent_c

MAC_FMT = '%02x:%02x:%02x:%02x:%02x:%02x'


class BaseFormat(ABC):
    @abstractmethod
    def encode(self, value):
        pass

    @classmethod
    @abstractmethod
    def decode(cls, data: bytes) -> tuple[Any, bytes]:
        pass

    def fromjson(self, data):
        return data

    def tojson(self, data):
        return data

    @abstractmethod
    def get_min_size(self):
        pass

    @abstractmethod
    def get_c_parts(self) -> tuple[str, str]:
        pass

    def get_c_code(self, name) -> str:
        pre, post = self.get_c_parts()
        return "%s %s%s;" % (pre, name, post)


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

    c_types = {
        "B": "uint8_t",
        "H": "uint16_t",
        "I": "uint32_t",
        "b": "int8_t",
        "h": "int16_t",
        "i": "int32_t",
        "s": "char",
    }

    def get_c_parts(self):
        return self.c_type, ("" if self.num == 1 else ("[%d]" % self.num))


class BoolFormat(SimpleFormat):
    def __init__(self):
        super().__init__('B')

    def encode(self, value):
        return super().encode(int(value))

    def decode(self, data: bytes) -> tuple[bool, bytes]:
        value, data = super().decode(data)
        return bool(value), data


class FixedStrFormat(SimpleFormat):
    def __init__(self, num):
        self.num = num
        super().__init__('%ds' % self.num)

    def encode(self, value: str):
        return value.encode()[:self.num].ljust(self.num, bytes((0, ))),

    def decode(self, data: bytes) -> tuple[str, bytes]:
        return data[:self.num].rstrip(bytes((0,))).decode(), data[self.num:]


class FixedHexFormat(SimpleFormat):
    def __init__(self, num, sep=''):
        self.num = num
        self.sep = sep
        super().__init__('%dB' % self.num)

    def encode(self, value: str):
        return super().encode(tuple(bytes.fromhex(value.replace(':', ''))))

    def decode(self, data: bytes) -> tuple[str, bytes]:
        return self.sep.join(('%02x' % i) for i in data[:self.num]), data[self.num:]


@abstractmethod
class BaseVarFormat(BaseFormat, ABC):
    def __init__(self, num_fmt='B'):
        self.num_fmt = num_fmt
        self.num_size = struct.calcsize(self.num_fmt)

    def get_min_size(self):
        return self.num_size

    def get_num_c_code(self):
        return SimpleFormat(self.num_fmt).get_c_code("num")


class VarArrayFormat(BaseVarFormat):
    def __init__(self, child_type, num_fmt='B'):
        super().__init__(num_fmt=num_fmt)
        self.child_type = child_type
        self.child_size = self.child_type.get_min_size()

    def encode(self, values: Sequence) -> bytes:
        data = struct.pack(self.num_fmt, (len(values),))
        for value in values:
            data += self.child_type.encode(value)
        return data

    def decode(self, data: bytes) -> tuple[list[Any], bytes]:
        num = struct.unpack(self.num_fmt, data[:self.num_size])[0]
        data = data[self.num_size:]
        result = []
        for i in range(num):
            item, data = self.child_type.decode(data)
            result.append(item)
        return result, data

    def get_c_parts(self):
        pre, post = self.child_type.get_c_parts()
        return super().get_num_c_code()+"\n"+pre, "[0]"+post


class VarStrFormat(BaseVarFormat):
    def encode(self, value: str) -> bytes:
        return struct.pack(self.num_fmt, (len(str),))+value.encode()

    def decode(self, data: bytes) -> tuple[str, bytes]:
        num = struct.unpack(self.num_fmt, data[:self.num_size])[0]
        return data[self.num_size:self.num_size+num].rstrip(bytes((0,))).decode(), data[self.num_size+num:]

    def get_c_parts(self):
        return super().get_num_c_code()+"\n"+"char", "[0]"


""" TPYES """

def normalize_name(name):
    if '_' in name:
        return name.lower()
    return re.sub(
        r"([a-z])([A-Z])",
        r"\1_\2",
        name
    ).lower()

@dataclass
class StructType:
    _union_options = {}
    union_type_field = None

    # noinspection PyMethodOverriding
    def __init_subclass__(cls, /, union_type_field=None, **kwargs):
        cls.union_type_field = union_type_field
        if union_type_field:
            if union_type_field in cls._union_options:
                raise TypeError('Duplicate union_type_field: %s', union_type_field)
            cls._union_options[union_type_field] = {}
        for key, values in cls._union_options.items():
            value = kwargs.pop(key, None)
            if value is not None:
                if value in values:
                    raise TypeError('Duplicate %s: %s', (key, value))
                values[value] = cls
                setattr(cls, key, value)
        super().__init_subclass__(**kwargs)

    @classmethod
    def get_types(cls):
        if not cls.union_type_field:
            raise TypeError('Not a union class')
        return cls._union_options[cls.union_type_field]

    @classmethod
    def get_type(cls, type_id) -> Self:
        if not cls.union_type_field:
            raise TypeError('Not a union class')
        return cls.get_types()[type_id]

    @classmethod
    def encode(cls, instance, ignore_fields=()) -> bytes:
        data = bytes()
        if cls.union_type_field and type(instance) is not cls:
            if not isinstance(instance, cls):
                raise ValueError('expected value of type %r, got %r' % (cls, instance))

            for field_ in fields(cls):
                data += field_.metadata["format"].encode(getattr(instance, field_.name))

            # todo: better
            data += instance.encode(instance, ignore_fields=set(f.name for f in fields(cls)))
            return data

        for field_ in fields(cls):
            if field_.name in ignore_fields:
                continue
            value = getattr(instance, field_.name)
            if "format" in field_.metadata:
                data += field_.metadata["format"].encode(value)
            elif issubclass(field_.type, StructType):
                if not isinstance(value, field_.type):
                    raise ValueError('expected value of type %r for %s.%s, got %r' %
                                    (field_.type, cls.__name__, field_.name, value))
                data += value.encode(value)
            else:
                raise TypeError('field %s.%s has no format and is no StructType' %
                                (cls.__class__.__name__, field_.name))
        return data

    @classmethod
    def decode(cls, data: bytes) -> Self:
        orig_data = data
        kwargs = {}
        no_init_data = {}
        for field_ in fields(cls):
            if "format" in field_.metadata:
                value, data = field_.metadata["format"].decode(data)
            elif issubclass(field_.type, StructType):
                value, data = field_.type.decode(data)
            else:
                raise TypeError('field %s.%s has no format and is no StructType' %
                                (cls.__name__, field_.name))
            if field_.init:
                kwargs[field_.name] = value
            else:
                no_init_data[field_.name] = value

        if cls.union_type_field:
            try:
                type_value = no_init_data[cls.union_type_field]
            except KeyError:
                raise TypeError('union_type_field %s.%s is missing' %
                                (cls.__name__, cls.union_type_field))
            try:
                klass = cls.get_type(type_value)
            except KeyError:
                raise TypeError('union_type_field %s.%s value %r no known' %
                                (cls.__name__, cls.union_type_field, type_value))
            return klass.decode(orig_data)
        return cls(**kwargs), data

    @classmethod
    def tojson(cls, instance) -> dict:
        result = {}

        if cls.union_type_field and type(instance) is not cls:
            if not isinstance(instance, cls):
                raise ValueError('expected value of type %r, got %r' % (cls, instance))

            for field_ in fields(instance):
                if field_.name is cls.union_type_field:
                    result[field_.name] = field_.metadata["format"].tojson(getattr(instance, field_.name))
                    break
            else:
                raise TypeError('couldn\'t find %s value' % cls.union_type_field)

            result.update(instance.tojson(instance))
            return result

        for field_ in fields(cls):
            value = getattr(instance, field_.name)
            if "format" in field_.metadata:
                result[field_.name] = field_.metadata["format"].tojson(value)
            elif issubclass(field_.type, StructType):
                if not isinstance(value, field_.type):
                    raise ValueError('expected value of type %r for %s.%s, got %r' %
                                     (field_.type, cls.__name__, field_.name, value))
                result[field_.name] = value.tojson(value)
            else:
                raise TypeError('field %s.%s has no format and is no StructType' %
                                (cls.__class__.__name__, field_.name))
        return result

    @classmethod
    def upgrade_json(cls, data):
        return data

    @classmethod
    def fromjson(cls, data: dict):
        data = data.copy()

        # todo: upgrade_json
        cls.upgrade_json(data)

        kwargs = {}
        no_init_data = {}
        for field_ in fields(cls):
            raw_value = data.get(field_.name, None)
            if "format" in field_.metadata:
                value = field_.metadata["format"].fromjson(raw_value)
            elif issubclass(field_.type, StructType):
                value = field_.type.fromjson(raw_value)
            else:
                raise TypeError('field %s.%s has no format and is no StructType' %
                                (cls.__name__, field_.name))
            if field_.init:
                kwargs[field_.name] = value
            else:
                no_init_data[field_.name] = value

        if cls.union_type_field:
            try:
                type_value = no_init_data.pop(cls.union_type_field)
            except KeyError:
                raise TypeError('union_type_field %s.%s is missing' %
                                (cls.__name__, cls.union_type_field))
            try:
                klass = cls.get_type(type_value)
            except KeyError:
                raise TypeError('union_type_field %s.%s value 0x%02x no known' %
                                (cls.__name__, cls.union_type_field, type_value))
            return klass.fromjson(data)

        return cls(**kwargs)

    @classmethod
    def get_c_parts(cls, ignore_fields=None, no_empty=False, typedef=False, union_only=False,
                    union_member_as_types=False):
        ignore_fields = set() if not ignore_fields else set(ignore_fields)

        pre = ""

        items = []
        for field_ in fields(cls):
            if field_.name in ignore_fields:
                continue
            name = field_.metadata.get("c_name", field_.name)
            if "format" in field_.metadata:
                items.append((
                    field_.metadata["format"].get_c_code(name),
                    field_.metadata.get("doc", None),
                )),
            elif issubclass(field_.type, StructType):
                items.append((
                    field_.type.get_c_code(name, typedef=False),
                    field_.metadata.get("doc", None),
                ))
            else:
                raise TypeError('field %s.%s has no format and is no StructType' %
                                (cls.__name__, field_.name))

        if cls.union_type_field:
            parent_fields = set(field_.name for field_ in fields(cls))
            union_items = []
            for key, option in cls.get_types().items():
                base_name = normalize_name(getattr(key, 'name', option.__name__))
                if union_member_as_types:
                    struct_name = cls.get_struct_name(base_name)
                    pre += option.get_c_code(
                        struct_name,
                        ignore_fields=(ignore_fields | parent_fields),
                        typedef=True
                    )+"\n\n"
                    union_items.append(
                        "%s %s;" % (struct_name, cls.get_variable_name(base_name)),
                    )
                else:
                    union_items.append(
                        option.get_c_code(base_name, ignore_fields=(ignore_fields | parent_fields))
                    )
            union_items.append(
                "uint8_t bytes[%s];" % max(
                    (option.get_min_size() for option in cls.get_types().values()),
                    default=0,
                )
            )
            union_code = "{\n"+indent_c("\n".join(union_items))+"\n}",
            if union_only:
                return "typedef union __packed %s" % union_code, "";
            else:
                items.append(("union %s;" % union_code, ""))
        elif union_only:
            return "", ""

        if no_empty and not items:
            return "", ""

        # todo: struct comment
        if typedef:
            comment = cls.__doc__.strip()
            if comment:
                pre += "/** %s */\n" % comment
            pre += "typedef struct __packed "
        else:
            pre += "struct "

        pre += "{\n%(elements)s\n}" % {
            "elements": indent_c(
                "\n".join(
                    code + ("" if not comment else (" /** %s */" % comment))
                    for code, comment in items
                )
            ),
        }
        return pre, ""

    @classmethod
    def get_c_code(cls, name=None, ignore_fields=None, no_empty=False, typedef=True, union_only=False,
                   union_member_as_types=False) -> str:
        pre, post = cls.get_c_parts(ignore_fields=ignore_fields, no_empty=no_empty, typedef=typedef,
                                    union_only=union_only, union_member_as_types=union_member_as_types,
                                    )
        if no_empty and not pre and not post:
            return ""
        return "%s %s%s;" % (pre, name, post)

    @classmethod
    def get_variable_name(cls, base_name):
        return base_name

    @classmethod
    def get_struct_name(cls, base_name):
        return "%s_t" % base_name

    @classmethod
    def get_min_size(cls) -> int:
        if cls.union_type_field:
            return (
                {f.name: field for f in fields()}[cls.union_type_field].metadata["format"].get_min_size() +
                sum((option.get_min_size() for option in cls.get_types().values()), start=0)
            )
        return sum((f.metadata.get("format", f.type).get_min_size() for f in fields(cls)), start=0)


class MacAddressFormat(FixedHexFormat):
    def __init__(self):
        super().__init__(num=6, sep=':')


class MacAddressesListFormat(VarArrayFormat):
    def __init__(self):
        super().__init__(child_type=MacAddressFormat())


""" stuff """

@unique
class LedType(IntEnum):
    SERIAL = 1
    MULTIPIN = 2

@dataclass
class LedConfig(StructType, union_type_field="led_type"):
    led_type: LedType = field(init=False, repr=False, metadata={"format": SimpleFormat('B')})


@dataclass
class SerialLedConfig(LedConfig, StructType, led_type=LedType.SERIAL):
    gpio: int = field(metadata={"format": SimpleFormat('B')})
    rmt: int = field(metadata={"format": SimpleFormat('B')})


@dataclass
class MultipinLedConfig(LedConfig, StructType, led_type=LedType.MULTIPIN):
    gpio_red: int = field(metadata={"format": SimpleFormat('B')})
    gpio_green: int = field(metadata={"format": SimpleFormat('B')})
    gpio_blue: int = field(metadata={"format": SimpleFormat('B')})


@dataclass
class RangeItemType(StructType):
    address: str = field(metadata={"format": MacAddressFormat()})
    distance: int = field(metadata={"format": SimpleFormat('H')})
