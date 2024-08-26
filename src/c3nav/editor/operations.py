import datetime
from typing import TypeAlias, Any, Annotated, Literal, Union

from django.db import models
from django.utils import timezone
from pydantic.config import ConfigDict
from pydantic.fields import Field
from pydantic.types import Discriminator

from c3nav.api.schema import BaseSchema

FieldValuesDict: TypeAlias = dict[str, Any]


class ObjectReference(BaseSchema):
    model_config = ConfigDict(frozen=True)
    model: str
    id: int

    @classmethod
    def from_instance(cls, instance: models.Model):
        """
        This method will not convert the ID yet!
        """
        return cls(model=instance._meta.model_name, id=instance.pk)


class BaseOperation(BaseSchema):
    obj: ObjectReference
    datetime: Annotated[datetime.datetime, Field(default_factory=timezone.now)]


class CreateObjectOperation(BaseOperation):
    type: Literal["create"] = "create"
    fields: FieldValuesDict


class UpdateObjectOperation(BaseOperation):
    type: Literal["update"] = "update"
    fields: FieldValuesDict


class DeleteObjectOperation(BaseOperation):
    type: Literal["delete"] = "delete"


class UpdateManyToManyOperation(BaseOperation):
    type: Literal["m2m_add"] = "m2m_update"
    field: str
    add_values: set[int] = set()
    remove_values: set[int] = set()


class ClearManyToManyOperation(BaseOperation):
    type: Literal["m2m_clear"] = "m2m_clear"
    field: str


DatabaseOperation = Annotated[
    Union[
        CreateObjectOperation,
        UpdateObjectOperation,
        DeleteObjectOperation,
        UpdateManyToManyOperation,
        ClearManyToManyOperation,
    ],
    Discriminator("type"),
]


class CollectedChanges(BaseSchema):
    prev_reprs: dict[ObjectReference, str] = {}
    prev_values: dict[ObjectReference, FieldValuesDict] = {}
    operations: list[DatabaseOperation] = []