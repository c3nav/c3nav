import re
import struct
from abc import ABC, abstractmethod
from dataclasses import Field, dataclass
from dataclasses import fields as dataclass_fields
from typing import Any, Self, Sequence

from pydantic import create_model

from c3nav.mesh.utils import indent_c


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

    def fromjson(self, data):
        return data

    def tojson(self, data):
        return data

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

    def set_field_type(self, field_type):
        self.field_type = field_type

    def get_c_definitions(self) -> dict[str, str]:
        return {}

    def get_typedef_name(self):
        return '%s_t' % normalize_name(self.field_type.__name__)


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
    def __init__(self, fmt="B", *, as_hex=False, c_definition=True):
        super().__init__(fmt)
        self.as_hex = as_hex
        self.c_definition = c_definition

    def set_field_type(self, field_type):
        super().set_field_type(field_type)
        self.c_struct_name = normalize_name(field_type.__name__) + '_t'

    def decode(self, data: bytes) -> tuple[Any, bytes]:
        value, out_data = super().decode(data)
        return self.field_type(value), out_data

    def get_c_parts(self):
        if not self.c_definition:
            return super().get_c_parts()
        return self.c_struct_name, ""

    def fromjson(self, data):
        return self.field_type[data]

    def tojson(self, data):
        return data.name

    def get_c_definitions(self) -> dict[str, str]:
        if not self.c_definition:
            return {}
        prefix = normalize_name(self.field_type.__name__).upper()
        options = []
        last_value = None
        for item in self.field_type:
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
    def __init__(self):
        super().__init__('B')

    def decode(self, data: bytes) -> tuple[bool, bytes]:
        fields = dataclass_fields(self.field_type)
        value, data = super().decode(data)
        return self.field_type(fields[0].type(value // 2 ** 4), fields[1].type(value // 2 ** 4)), data

    def encode(self, value):
        fields = dataclass_fields(self.field_type)
        return super().encode(
            getattr(value, fields[0].name).value * 2 ** 4 +
            getattr(value, fields[1].name).value * 2 ** 4
        )

    def fromjson(self, data):
        fields = dataclass_fields(self.field_type)
        return self.field_type(*(field.type[data[field.name]] for field in fields))

    def tojson(self, data):
        fields = dataclass_fields(self.field_type)
        return {
            field.name: getattr(data, field.name).name for field in fields
        }


class ChipRevFormat(SimpleFormat):
    def __init__(self):
        super().__init__('H')

    def decode(self, data: bytes) -> tuple[tuple[int, int], bytes]:
        value, data = super().decode(data)
        return (value // 100, value % 100), data

    def encode(self, value):
        return value[0] * 100 + value[1]


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

    def fromjson(self, data):
        return [
            self.child_type.fromjson(item) for item in data
        ]

    def tojson(self, data):
        return [
            self.child_type.tojson(item) for item in data
        ]

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


@dataclass
class StructType:
    _union_options = {}
    union_type_field = None
    existing_c_struct = None

    # noinspection PyMethodOverriding
    def __init_subclass__(cls, /, union_type_field=None, existing_c_struct=None, **kwargs):
        cls.union_type_field = union_type_field
        if cls.existing_c_struct is not None:
            # TODO: can we make it possible? does it even make sense?
            raise TypeError('subclassing an external c struct is not possible')
        cls.existing_c_struct = existing_c_struct
        if union_type_field:
            if union_type_field in cls._union_options:
                raise TypeError('Duplicate union_type_field: %s', union_type_field)
            cls._union_options[union_type_field] = {}
            f = getattr(cls, union_type_field)
            metadata = dict(f.metadata)
            metadata['union_discriminator'] = True
            f.metadata = metadata
            f.repr = False
            f.init = False

        for attr_name in cls.__dict__.keys():
            attr = getattr(cls, attr_name)
            if isinstance(attr, Field):
                metadata = dict(attr.metadata)
                if "defining_class" not in metadata:
                    metadata["defining_class"] = cls
                    if "format" in metadata:
                        metadata["format"].set_field_type(cls.__annotations__[attr_name])

                attr.metadata = metadata

        for key, values in cls._union_options.items():
            value = kwargs.pop(key, None)
            if value is not None:
                if value in values:
                    raise TypeError('Duplicate %s: %s', (key, value))
                values[value] = cls
                setattr(cls, key, value)

        # pydantic model
        cls._pydantic_fields = getattr(cls, '_pydantic_fields', {}).copy()
        fields = []
        for field_ in dataclass_fields(cls):
            fields.append((field_.name, field_.type, field_.metadata))
        for attr_name in tuple(cls.__annotations__.keys()):
            attr = getattr(cls, attr_name, None)
            metadata = attr.metadata if isinstance(attr, Field) else {}
            try:
                type_ = cls.__annotations__[attr_name]
            except KeyError:
                # print('nope', cls, attr_name)
                continue
            fields.append((attr_name, type_, metadata))
        for name, type_, metadata in fields:
            if metadata.get("format", None):
                cls._pydantic_fields[name] = (type_, ...)
            elif issubclass(type_, StructType):
                if metadata.get("json_embed"):
                    cls._pydantic_fields.update(type_._pydantic_fields)
                else:
                    cls._pydantic_fields[name] = (type_.schema, ...)
            else:
                raise TypeError('field %s.%s has no format and is no StructType' %
                                (cls.__class__.__name__, name))
        cls.schema = create_model(cls.__name__ + 'Schema', **cls._pydantic_fields)
        super().__init_subclass__(**kwargs)

    @classmethod
    def get_var_num(cls):
        return sum([f.metadata.get("format", f.type).get_var_num() for f in dataclass_fields(cls)], start=0)

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

            for field_ in dataclass_fields(cls):
                data += field_.metadata["format"].encode(getattr(instance, field_.name))

            # todo: better
            data += instance.encode(instance, ignore_fields=set(f.name for f in dataclass_fields(cls)))
            return data

        for field_ in dataclass_fields(cls):
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
    def decode(cls, data: bytes) -> tuple[Self, bytes]:
        orig_data = data
        kwargs = {}
        no_init_data = {}
        for field_ in dataclass_fields(cls):
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

            for field_ in dataclass_fields(instance):
                if field_.name is cls.union_type_field:
                    result[field_.name] = field_.metadata["format"].tojson(getattr(instance, field_.name))
                    break
            else:
                raise TypeError('couldn\'t find %s value' % cls.union_type_field)

            result.update(instance.tojson(instance))
            return result

        for field_ in dataclass_fields(cls):
            value = getattr(instance, field_.name)
            if "format" in field_.metadata:
                result[field_.name] = field_.metadata["format"].tojson(value)
            elif issubclass(field_.type, StructType):
                if not isinstance(value, field_.type):
                    raise ValueError('expected value of type %r for %s.%s, got %r' %
                                     (field_.type, cls.__name__, field_.name, value))
                json_val = value.tojson(value)
                if field_.metadata.get("json_embed"):
                    for k, v in json_val.items():
                        result[k] = v
                else:
                    result[field_.name] = value.tojson(value)
            else:
                raise TypeError('field %s.%s has no format and is no StructType' %
                                (cls.__class__.__name__, field_.name))
        return result

    @classmethod
    def upgrade_json(cls, data):
        return data

    @classmethod
    def fromjson(cls, data: dict) -> Self:
        data = data.copy()

        # todo: upgrade_json
        cls.upgrade_json(data)

        kwargs = {}
        no_init_data = {}
        for field_ in dataclass_fields(cls):
            raw_value = data.get(field_.name, None)
            if "format" in field_.metadata:
                value = field_.metadata["format"].fromjson(raw_value)
            elif issubclass(field_.type, StructType):
                if field_.metadata.get("json_embed"):
                    value = field_.type.fromjson(data)
                else:
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
    def get_c_struct_items(cls, ignore_fields=None, no_empty=False, top_level=False, union_only=False, in_union=False):
        ignore_fields = set() if not ignore_fields else set(ignore_fields)

        items = []

        for field_ in dataclass_fields(cls):
            if field_.name in ignore_fields:
                continue
            if in_union and field_.metadata["defining_class"] != cls:
                continue

            name = field_.metadata.get("c_name", field_.name)
            if "format" in field_.metadata:
                if not field_.metadata.get("union_discriminator") or field_.metadata.get("defining_class") == cls:
                    items.append((
                        (
                            ("%(typedef_name)s %(name)s;" % {
                                "typedef_name": field_.metadata["format"].get_typedef_name(),
                                "name": name,
                            })
                            if field_.metadata.get("as_definition")
                            else field_.metadata["format"].get_c_code(name)
                        ),
                        field_.metadata.get("doc", None),
                    )),
            elif issubclass(field_.type, StructType):
                if field_.metadata.get("c_embed"):
                    embedded_items = field_.type.get_c_struct_items(ignore_fields, no_empty, top_level, union_only)
                    items.extend(embedded_items)
                else:
                    items.append((
                        (
                            ("%(typedef_name)s %(name)s;" % {
                                "typedef_name": field_.type.get_typedef_name(),
                                "name": name,
                            })
                            if field_.metadata.get("as_definition")
                            else field_.type.get_c_code(name, typedef=False)
                        ),
                        field_.metadata.get("doc", None),
                    )),
            else:
                raise TypeError('field %s.%s has no format and is no StructType' %
                                (cls.__name__, field_.name))

        if cls.union_type_field:
            if not union_only:
                union_code = cls.get_c_union_code(ignore_fields)
                items.append(("union __packed %s;" % union_code, ""))

        return items

    @classmethod
    def get_c_union_size(cls):
        return max(
            (option.get_min_size(no_inherited_fields=True) for option in
             cls._union_options[cls.union_type_field].values()),
            default=0,
        )

    @classmethod
    def get_c_definitions(cls) -> dict[str, str]:
        definitions = {}
        for field_ in dataclass_fields(cls):
            if "format" in field_.metadata:
                definitions.update(field_.metadata["format"].get_c_definitions())
                if field_.metadata.get("as_definition"):
                    typedef_name = field_.metadata["format"].get_typedef_name()
                    definitions[typedef_name] = 'typedef %(code)s %(name)s;' % {
                        "code": ''.join(field_.metadata["format"].get_c_parts()),
                        "name": typedef_name,
                    }
            elif issubclass(field_.type, StructType):
                definitions.update(field_.type.get_c_definitions())
                if field_.metadata.get("as_definition"):
                    typedef_name = field_.type.get_typedef_name()
                    definitions[typedef_name] = field_.type.get_c_code(name=typedef_name, typedef=True)
            else:
                raise TypeError('field %s.%s has no format and is no StructType' %
                                (cls.__name__, field_.name))
        if cls.union_type_field:
            for key, option in cls._union_options[cls.union_type_field].items():
                definitions.update(option.get_c_definitions())
        return definitions

    @classmethod
    def get_c_union_code(cls, ignore_fields=None):
        union_items = []
        for key, option in cls._union_options[cls.union_type_field].items():
            base_name = normalize_name(getattr(key, 'name', option.__name__))
            item_c_code = option.get_c_code(
                base_name, ignore_fields=ignore_fields, typedef=False, in_union=True, no_empty=True
            )
            if item_c_code:
                union_items.append(item_c_code)
        size = cls.get_c_union_size()
        union_items.append(
            "uint8_t bytes[%0d]; " % size
        )
        return "{\n" + indent_c("\n".join(union_items)) + "\n}"

    @classmethod
    def get_c_parts(cls, ignore_fields=None, no_empty=False, top_level=False, union_only=False, in_union=False):
        if cls.existing_c_struct is not None:
            return (cls.existing_c_struct, "")

        ignore_fields = set() if not ignore_fields else set(ignore_fields)

        if union_only:
            if cls.union_type_field:
                union_code = cls.get_c_union_code(ignore_fields)
                return "typedef union __packed %s" % union_code, ""
            else:
                return "", ""

        pre = ""

        items = cls.get_c_struct_items(ignore_fields=ignore_fields,
                                       no_empty=no_empty,
                                       top_level=top_level,
                                       union_only=union_only,
                                       in_union=in_union)

        if no_empty and not items:
            return "", ""

        # todo: struct comment
        if top_level:
            comment = cls.__doc__.strip()
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

    @classmethod
    def get_c_code(cls, name=None, ignore_fields=None, no_empty=False, typedef=True, union_only=False,
                   in_union=False) -> str:
        pre, post = cls.get_c_parts(ignore_fields=ignore_fields,
                                    no_empty=no_empty,
                                    top_level=typedef,
                                    union_only=union_only,
                                    in_union=in_union)
        if no_empty and not pre and not post:
            return ""
        return "%s %s%s;" % (pre, name, post)

    @classmethod
    def get_variable_name(cls, base_name):
        return base_name

    @classmethod
    def get_typedef_name(cls):
        return "%s_t" % normalize_name(cls.__name__)

    @classmethod
    def get_min_size(cls, no_inherited_fields=False) -> int:
        if cls.union_type_field:
            own_size = sum([f.metadata.get("format", f.type).get_min_size() for f in dataclass_fields(cls)])
            union_size = max(
                [0] + [option.get_min_size(True) for option in cls._union_options[cls.union_type_field].values()])
            return own_size + union_size
        if no_inherited_fields:
            relevant_fields = [f for f in dataclass_fields(cls) if f.metadata["defining_class"] == cls]
        else:
            relevant_fields = [f for f in dataclass_fields(cls) if not f.metadata.get("union_discriminator")]
        return sum((f.metadata.get("format", f.type).get_min_size() for f in relevant_fields), start=0)

    @classmethod
    def get_size(cls, no_inherited_fields=False, calculate_max=False) -> int:
        if cls.union_type_field:
            own_size = sum(
                [f.metadata.get("format", f.type).get_size(calculate_max=calculate_max) for f in dataclass_fields(cls)])
            union_size = max(
                [0] + [option.get_size(no_inherited_fields=True, calculate_max=calculate_max) for option in
                       cls._union_options[cls.union_type_field].values()])
            return own_size + union_size
        if no_inherited_fields:
            relevant_fields = [f for f in dataclass_fields(cls) if f.metadata["defining_class"] == cls]
        else:
            relevant_fields = [f for f in dataclass_fields(cls) if not f.metadata.get("union_discriminator")]
        return sum((f.metadata.get("format", f.type).get_size(calculate_max=calculate_max) for f in relevant_fields),
                   start=0)


def normalize_name(name):
    if '_' in name:
        name = name.lower()
    else:
        name = re.sub(
            r"([a-zA-Z])([A-Z][a-z])",
            r"\1_\2",
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
