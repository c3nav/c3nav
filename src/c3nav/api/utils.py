from typing import Annotated, Any, Type

import annotated_types
from pydantic import AfterValidator, GetCoreSchemaHandler, GetJsonSchemaHandler, PlainSerializer
from pydantic.json_schema import JsonSchemaValue, WithJsonSchema
from pydantic_core import CoreSchema, core_schema
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
    def __get_pydantic_json_schema__(
        cls, core_schema: CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        json_schema = handler(core_schema)
        json_schema = handler.resolve_ref_schema(json_schema)
        json_schema["enum"] = [m.name for m in cls]
        json_schema["type"] = "string"
        return json_schema

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: Type[Any], handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.no_info_after_validator_function(
            cls.validate,
            core_schema.any_schema(),
            serialization=core_schema.plain_serializer_function_ser_schema(lambda x: x.name),
        )

    @classmethod
    def validate(cls, v: int):
        if isinstance(v, cls):
            return v
        try:
            return cls[v]
        except KeyError:
            pass
        return cls(v)


NonEmptyStr = Annotated[str, annotated_types.MinLen(1)]
