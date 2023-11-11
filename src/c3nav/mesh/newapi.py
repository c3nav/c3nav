from datetime import datetime

from ninja import Router as APIRouter, Field as APIField, Schema
from ninja.pagination import paginate

from c3nav.mesh.dataformats import BoardType
from c3nav.mesh.messages import ChipType
from c3nav.mesh.models import FirmwareVersion

api_router = APIRouter(tags=["mesh"])


class FirmwareBuildSchema(Schema):
    id: int
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


class Error(Schema):
    detail: str


@api_router.get('/firmwares/', response=list[FirmwareSchema],
                summary="List available firmwares")
@paginate
def firmware_list(request):
    return FirmwareVersion.objects.all()


@api_router.get('/firmwares/{firmware_id}/', response={200: FirmwareSchema, 404: Error},
                summary="Get specific firmware")
def firmware_detail(request, firmware_id: int):
    try:
        return FirmwareVersion.objects.get(id=firmware_id)
    except FirmwareVersion.DoesNotExist:
        return 404, {"detail": "firmware not found"}
