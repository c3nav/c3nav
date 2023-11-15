import base64
from datetime import datetime

from django.db import transaction
from ninja import Field as APIField
from ninja import ModelSchema
from ninja import Router as APIRouter
from ninja import Schema, UploadedFile
from ninja.pagination import paginate
from pydantic import validator

from c3nav.api.newauth import BearerAuth, auth_permission_responses, auth_responses
from c3nav.mesh.dataformats import BoardType
from c3nav.mesh.messages import ChipType
from c3nav.mesh.models import FirmwareVersion

api_router = APIRouter(tags=["mesh"])


class FirmwareBuildSchema(Schema):
    id: int
    variant: str = APIField(..., example="c3uart")
    chip: ChipType = APIField(..., example=ChipType.ESP32_C3.name)
    sha256_hash: str = APIField(..., regex=r"^[0-9a-f]{64}$")
    url: str = APIField(..., alias="binary", example="/media/firmware/012345/firmware.bin")
    boards: list[BoardType] = APIField(..., example=[BoardType.C3NAV_LOCATION_PCB_REV_0_2.name, ])

    @staticmethod
    def resolve_chip(obj):
        # todo: do this in model? idk
        return ChipType(obj.chip)


class FirmwareSchema(Schema):
    id: int
    project_name: str = APIField(..., example="c3nav_positioning")
    version: str = APIField(..., example="499837d-dirty")
    idf_version: str = APIField(..., example="v5.1-476-g3187b8b326")
    created: datetime
    builds: list[FirmwareBuildSchema]

    @validator('builds')
    def builds_variants_must_be_unique(cls, builds):
        if len(set(build.variant for build in builds)) != len(builds):
            raise ValueError("builds must have unique variant identifiers")
        return builds


class Error(Schema):
    detail: str


@api_router.get('/firmwares/', summary="List available firmwares",
                response={200: list[FirmwareSchema], **auth_responses})
@paginate
def firmware_list(request):
    return FirmwareVersion.objects.all()


@api_router.get('/firmwares/{firmware_id}/', summary="Get specific firmware",
                response={200: FirmwareSchema, **auth_responses})
def firmware_detail(request, firmware_id: int):
    try:
        return FirmwareVersion.objects.get(id=firmware_id)
    except FirmwareVersion.DoesNotExist:
        return 404, {"detail": "firmware not found"}


class Base64Bytes(bytes):
    @classmethod
    def __get_validators__(cls):
        # one or more validators may be yielded which will be called in the
        # order to validate the input, each validator will receive as an input
        # the value returned from the previous validator
        yield cls.validate

    @classmethod
    def __modify_schema__(cls, field_schema):
        # __modify_schema__ should mutate the dict it receives in place,
        # the returned value will be ignored
        field_schema.update(
            # simplified regex here for brevity, see the wikipedia link above
            pattern='^[A-Z]{1,2}[0-9][A-Z0-9]? ?[0-9][A-Z]{2}$',
            # some example postcodes
            examples=['SP11 9DG', 'w1j7bu'],
        )

    @classmethod
    def validate(cls, v):
        if not isinstance(v, str):
            raise TypeError('string required')
        return cls(base64.b64decode(v.encode("ascii")))

    def __repr__(self):
        return f'PostCode({super().__repr__()})'


class UploadFirmwareBuildSchema(Schema):
    variant: str = APIField(..., example="c3uart")
    chip: ChipType = APIField(..., example=ChipType.ESP32_C3.name)
    sha256_hash: str = APIField(..., regex=r"^[0-9a-f]{64}$")
    boards: list[BoardType] = APIField(..., example=[BoardType.C3NAV_LOCATION_PCB_REV_0_2.name, ])
    binary: bytes = APIField(..., example="base64", contentEncoding="base64")

    @validator('binary')
    def get_binary_base64(cls, binary):
        return base64.b64decode(binary.encode())


class UploadFirmwareSchema(Schema):
    project_name: str = APIField(..., example="c3nav_positioning")
    version: str = APIField(..., example="499837d-dirty")
    idf_version: str = APIField(..., example="v5.1-476-g3187b8b326")
    builds: list[UploadFirmwareBuildSchema] = APIField(..., min_items=1)

    @validator('builds')
    def builds_variants_must_be_unique(cls, builds):
        if len(set(build.variant for build in builds)) != len(builds):
            raise ValueError("builds must have unique variant identifiers")
        return builds


@api_router.post('/firmwares/upload', summary="Upload firmware", auth=BearerAuth(superuser=True),
                 response={200: FirmwareSchema, **auth_permission_responses})
def firmware_upload(request, firmware_data: UploadFirmwareSchema):
    raise NotImplementedError
