from enum import EnumMeta
from typing import Any, Callable, Iterator, Optional, cast

from pydantic.fields import ModelField
from rest_framework.exceptions import ParseError


def get_api_post_data(request):
    is_json = request.META.get('CONTENT_TYPE').lower() == 'application/json'
    if is_json:
        try:
            data = request.json_body
        except AttributeError:
            raise ParseError('Invalid JSON.')
        return data
    return request.POST


class EnumSchemaByNameMixin:
    @classmethod
    def __modify_schema__(cls, field_schema: dict[str, Any], field: Optional[ModelField]) -> None:
        if field is None:
            return
        field_schema["enum"] = list(cast(EnumMeta, field.type_).__members__.keys())
        field_schema["type"] = "string"

    @classmethod
    def _validate(cls, v: Any, field: ModelField) -> Any:
        if isinstance(v, cls):
            # it's already the object, so it's going to json, return string
            return v.name
        try:
            # it's a string, so it's coming from json, return object
            return cls[v]
        except KeyError:
            raise ValueError(f"Invalid value for {cls}: `{v}`")

    @classmethod
    def __get_validators__(cls) -> Iterator[Callable[..., Any]]:
        yield cls._validate
