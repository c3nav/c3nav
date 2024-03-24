import string
from collections import UserDict, namedtuple
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import cached_property
from operator import attrgetter
from typing import Any, Mapping, Optional, Self

import channels
from django.contrib.auth import get_user_model
from django.core.validators import RegexValidator
from django.db import NotSupportedError, models
from django.db.models import Q, UniqueConstraint
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from c3nav.mapdata.models.geometry.space import RangingBeacon
from c3nav.mesh.schemas import BoardType, ChipType, FirmwareImage
from c3nav.mesh.messages import ConfigFirmwareMessage, ConfigHardwareMessage
from c3nav.mesh.messages import MeshMessage as MeshMessage
from c3nav.mesh.messages import MeshMessageType
from c3nav.mesh.utils import MESH_ALL_OTA_GROUP, UPLINK_TIMEOUT
from c3nav.routing.locator import Locator

FirmwareLookup = namedtuple('FirmwareLookup', ('sha256_hash', 'chip', 'project_name', 'version', 'idf_version'))


@dataclass
class FirmwareDescription:
    chip: ChipType
    project_name: str
    version: str
    idf_version: str
    sha256_hash: str
    build: Optional["FirmwareBuild"] = None
    created: datetime | None = None

    def get_lookup(self) -> FirmwareLookup:
        return FirmwareLookup(
            chip=self.chip,
            project_name=self.project_name,
            version=self.version,
            idf_version=self.idf_version,
            sha256_hash=self.sha256_hash,
        )


@dataclass(frozen=True)
class HardwareDescription:
    chip: ChipType
    board: BoardType


class MeshNodeQuerySet(models.QuerySet):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._prefetch_last_messages = set()
        self._prefetch_last_messages_done = False
        self._prefetch_firmwares = False
        self._prefetch_ota = False
        self._prefetch_ota_done = False
        self._prefetch_ranging_beacon = False
        self._prefetch_ranging_beacon_done = False

    def _clone(self):
        clone = super()._clone()
        clone._prefetch_last_messages = self._prefetch_last_messages
        clone._prefetch_firmwares = self._prefetch_firmwares
        clone._prefetch_ota = self._prefetch_ota
        clone._prefetch_ranging_beacon = self._prefetch_ranging_beacon
        return clone

    def prefetch_last_messages(self, *types: MeshMessageType):
        clone = self._chain()
        clone._prefetch_last_messages |= (
            set(types) if types else set(msgtype for msgtype in MeshMessageType)
        )
        return clone

    def prefetch_firmwares(self):
        clone = self.prefetch_last_messages(MeshMessageType.CONFIG_FIRMWARE,
                                            MeshMessageType.CONFIG_HARDWARE)
        clone._prefetch_firmwares = True
        return clone

    def prefetch_ota(self):
        clone = self._chain()
        clone._prefetch_ota = True
        return clone

    def prefetch_ranging_beacon(self):
        clone = self._chain()
        clone._prefetch_ranging_beacon = True
        return clone

    def _fetch_all(self):
        super()._fetch_all()
        nodes = None
        if self._prefetch_last_messages and not self._prefetch_last_messages_done:
            nodes: dict[str, MeshNode] = {node.pk: node for node in self._result_cache}
            try:
                for message in NodeMessage.objects.order_by('message_type', 'src_node', '-datetime', '-pk').filter(
                        message_type__in=(t.name for t in self._prefetch_last_messages),
                        src_node__in=nodes.keys(),
                ).prefetch_related("uplink").distinct('message_type', 'src_node'):
                    nodes[message.src_node_id].last_messages[message.message_type] = message
                for node in nodes.values():
                    node.last_messages["any"] = (
                        max(node.last_messages.values(), key=attrgetter("datetime"))
                        if node.last_messages else None
                    )
                self._prefetch_last_messages_done = True
            except NotSupportedError:
                pass

            if self._prefetch_firmwares:
                # fetch matching firmware builds
                firmwares = {
                    fw_desc.get_lookup(): fw_desc for fw_desc in
                    (build.firmware_description for build in FirmwareBuild.objects.filter(
                        sha256_hash__in=set(
                            node.last_messages[MeshMessageType.CONFIG_FIRMWARE].parsed.app_desc.app_elf_sha256
                            for node in self._result_cache
                            if node.last_messages[MeshMessageType.CONFIG_FIRMWARE]
                        )
                    ))
                }

                # assign firmware descriptions
                for node in nodes.values():
                    firmware_desc = node.firmware_description
                    node._firmware_description = (
                        firmwares.get(firmware_desc.get_lookup(), firmware_desc)
                        if firmware_desc else None
                    )

                # get date of first appearance
                nodes_to_complete = tuple(
                    node for node in nodes.values()
                    if node._firmware_description and node._firmware_description.build is None
                )
                try:
                    created_lookup = {
                        msg.parsed.app_desc.app_elf_sha256: msg.datetime
                        for msg in NodeMessage.objects.filter(
                            message_type=MeshMessageType.CONFIG_FIRMWARE.name,
                            data__app_elf_sha256__in=(node._firmware_description.sha256_hash
                                                      for node in nodes_to_complete)
                        ).order_by('data__app_elf_sha256', 'datetime').distinct('data__app_elf_sha256')
                    }
                    print(created_lookup)
                except NotSupportedError:
                    created_lookup = {
                        app_elf_sha256: NodeMessage.objects.filter(
                            message_type=MeshMessageType.CONFIG_FIRMWARE.name,
                            data__app_elf_sha256=app_elf_sha256
                        ).order_by('datetime').first()
                        for app_elf_sha256 in {node._firmware_description.sha256_hash for node in nodes_to_complete}
                    }
                for node in nodes_to_complete:
                    node._firmware_description.created = created_lookup[node._firmware_description.sha256_hash]

        if self._prefetch_ota and not self._prefetch_ota_done:
            if nodes is None:
                nodes: dict[str, MeshNode] = {node.pk: node for node in self._result_cache}
            try:
                for ota in OTAUpdateRecipient.objects.filter(
                        node__in=nodes.keys(),
                        status=OTARecipientStatus.RUNNING,
                ).select_related("update", "update__build"):
                    # noinspection PyUnresolvedReferences
                    nodes[ota.node_id]._current_ota = ota
                for node in nodes.values():
                    if not hasattr(node, "_current_ota"):
                        node._current_ota = None
                self._prefetch_ota_done = True
            except NotSupportedError:
                pass

        if self._prefetch_ranging_beacon and not self._prefetch_ranging_beacon_done:
            if nodes is None:
                nodes: dict[str, MeshNode] = {node.pk: node for node in self._result_cache}
            try:
                for ranging_beacon in RangingBeacon.objects.filter(wifi_bssid__in=nodes.keys()).select_related('space'):
                    # noinspection PyUnresolvedReferences
                    nodes[ranging_beacon.bssid]._ranging_beacon = ranging_beacon
                for node in nodes.values():
                    if not hasattr(node, "_ranging_beacon"):
                        node._ranging_beacon = None
                self._prefetch_ranging_beacon_done = True
            except NotSupportedError:
                pass


class LastMessagesByTypeLookup(UserDict):
    def __init__(self, node):
        super().__init__()
        self.node = node

    def _get_key(self, item):
        if isinstance(item, MeshMessageType):
            return item
        if isinstance(item, str):
            try:
                return getattr(MeshMessageType, item)
            except AttributeError:
                pass
        return MeshMessageType(item)

    def __getitem__(self, key):
        if key == "any":
            msg = self.node.received_messages.order_by('-datetime', '-pk').first()
            self.data["any"] = msg
            return msg
        key = self._get_key(key)
        try:
            return self.data[key]
        except KeyError:
            pass
        msg = self.node.received_messages.filter(message_type=key.name).order_by('-datetime', '-pk').first()
        self.data[key] = msg
        return msg

    def __setitem__(self, key, item):
        if key == "any":
            self.data["any"] = item
            return
        self.data[self._get_key(key)] = item


class MeshNode(models.Model):
    """
    A nesh node. Any node.
    """
    address = models.CharField(_('mac address'), max_length=17, primary_key=True,
                               validators=[RegexValidator(
                                   regex='^([a-f0-9]{2}:){5}[a-f0-9]{2}$',
                                   message='Must be a lower-case mac address',
                                   code='invalid_macaddress'
                               )])

    name = models.CharField(_('name'), max_length=32, null=True, blank=True)
    first_seen = models.DateTimeField(_('first seen'), auto_now_add=True)
    uplink = models.ForeignKey('MeshUplink', models.PROTECT, null=True,
                               related_name='routed_nodes', verbose_name=_('uplink'))
    last_signin = models.DateTimeField(_('last signin'), null=True)
    objects = models.Manager.from_queryset(MeshNodeQuerySet)()

    def __str__(self):
        if self.name:
            return '%s (%s)' % (self.address, self.name)
        return self.address

    @cached_property
    def last_messages(self) -> Mapping[Any, "NodeMessage"]:
        return LastMessagesByTypeLookup(self)

    @cached_property
    def current_ota(self) -> Optional["OTAUpdateRecipient"]:
        try:
            # noinspection PyUnresolvedReferences
            return self._current_ota
        except AttributeError:
            return self.ota_updates.select_related("update", "update__build").filter(
                status=OTARecipientStatus.RUNNING
            ).first()

    @cached_property
    def ranging_beacon(self) -> Optional["RangingBeacon"]:
        try:
            # noinspection PyUnresolvedReferences
            return self._ranging_beacon
        except AttributeError:
            return RangingBeacon.objects.filter(bssid=self.address).first()

    # noinspection PyUnresolvedReferences
    @property
    def firmware_description(self) -> Optional[FirmwareDescription]:
        with suppress(AttributeError):
            return self._firmware_description

        fw_msg = self.last_messages[MeshMessageType.CONFIG_FIRMWARE]
        hw_msg = self.last_messages[MeshMessageType.CONFIG_HARDWARE]
        if not fw_msg or not hw_msg:
            return None

        # noinspection PyTypeChecker
        firmware_msg: ConfigFirmwareMessage = fw_msg.parsed
        # noinspection PyTypeChecker
        hardware_msg: ConfigHardwareMessage = hw_msg.parsed
        return FirmwareDescription(
            chip=hardware_msg.chip,
            project_name=firmware_msg.app_desc.project_name,
            version=firmware_msg.app_desc.version,
            idf_version=firmware_msg.app_desc.idf_version,
            sha256_hash=firmware_msg.app_desc.app_elf_sha256,
        )

    @cached_property
    def hardware_description(self) -> HardwareDescription:
        # noinspection PyUnresolvedReferences

        hw_msg = self.last_messages[MeshMessageType.CONFIG_HARDWARE]
        board_msg = self.last_messages[MeshMessageType.CONFIG_BOARD]
        return HardwareDescription(
            chip=hw_msg.parsed.chip if hw_msg else None,
            board=board_msg.parsed.board_config.board if board_msg else None,
        )

    # overriden by prefetch_firmwares()
    firmware_desc = None

    @cached_property
    def chip(self) -> ChipType:
        return self.last_messages[MeshMessageType.CONFIG_HARDWARE].parsed.chip

    @cached_property
    def board(self) -> ChipType:
        # noinspection PyUnresolvedReferences
        return self.last_messages[MeshMessageType.CONFIG_BOARD].parsed.board_config.board

    def get_uplink(self) -> Optional["MeshUplink"]:
        if self.uplink_id is None:
            return None
        if self.uplink.last_ping + timedelta(seconds=UPLINK_TIMEOUT) < timezone.now():
            return None
        return self.uplink

    @classmethod
    def get_node_and_uplink(self, address) -> Optional["MeshUplink"]:
        try:
            dst_node = MeshNode.objects.select_related('uplink').get(address=address)
        except MeshNode.DoesNotExist:
            return False
        return dst_node.get_uplink()

    def get_locator_xyz(self):
        try:
            locator = Locator.load()
        except FileNotFoundError:
            return None
        return locator.get_xyz(self.address)


class MeshUplink(models.Model):
    """
    An uplink session, a direct connection to a node
    """

    class EndReason(models.TextChoices):
        CLOSED = "closed", _("closed")
        REPLACED = "replaced", _("replaced")
        NEW_TIMEOUT = "new_timeout", _("new (timeout)")

    name = models.CharField(_('channel name'), max_length=128)
    started = models.DateTimeField(_('started'), auto_now_add=True)
    node = models.ForeignKey(MeshNode, models.PROTECT, related_name='uplink_sessions',
                             verbose_name=_('node'))
    last_ping = models.DateTimeField(_('last ping from consumer'))
    end_reason = models.CharField(_('end reason'), choices=EndReason.choices, null=True, max_length=16)

    class Meta:
        constraints = (
            UniqueConstraint(fields=["node"], condition=Q(end_reason__isnull=True), name='only_one_active_uplink'),
        )


class NodeMessage(models.Model):
    MESSAGE_TYPES = [(msgtype.name, msgtype.pretty_name) for msgtype in MeshMessageType]
    src_node = models.ForeignKey(MeshNode, models.PROTECT, related_name='received_messages',
                                 verbose_name=_('node'))
    uplink = models.ForeignKey(MeshUplink, models.PROTECT, related_name='relayed_messages',
                               verbose_name=_('uplink'))
    datetime = models.DateTimeField(_('datetime'), db_index=True, auto_now_add=True)
    message_type = models.CharField(_('message type'), max_length=24, db_index=True, choices=MESSAGE_TYPES)
    data = models.JSONField(_('message data'))

    def __str__(self):
        return '(#%d) %s at %s' % (self.pk, self.get_message_type_display(), self.datetime)

    @cached_property
    def parsed(self) -> Self:
        return MeshMessage.model_validate(self.data)


class FirmwareVersion(models.Model):
    project_name = models.CharField(_('project name'), max_length=32)
    version = models.CharField(_('firmware version'), max_length=32, unique=True)
    idf_version = models.CharField(_('IDF version'), max_length=32)
    uploader = models.ForeignKey(get_user_model(), null=True, on_delete=models.SET_NULL)
    created = models.DateTimeField(_('creation/upload date'), auto_now_add=True)

    def serialize(self):
        return {
            'project_name': self.project_name,
            'version': self.version,
            'idf_version': self.idf_version,
            'created': self.created.isoformat(),
            'builds': {
                build.variant: build.serialize()
                for build in self.builds.all().prefetch_related("firmwarebuildboard_set")
            }
        }


def firmware_upload_path(instance, filename):
    # file will be uploaded to MEDIA_ROOT/user_<id>/<filename>
    version = slugify(instance.version.version)
    variant = slugify(instance.variant)
    random_string = get_random_string(32, string.ascii_letters + string.digits)
    return f"firmware/{version}/{variant}/{random_string}/{filename}"


class FirmwareBuild(models.Model):
    CHIPS = [(chiptype.value, chiptype.pretty_name) for chiptype in ChipType]

    version = models.ForeignKey(FirmwareVersion, related_name='builds', on_delete=models.CASCADE)
    variant = models.CharField(_('variant name'), max_length=64)
    chip = models.SmallIntegerField(_('chip'), db_index=True, choices=CHIPS)
    sha256_hash = models.CharField(_('SHA256 hash'), unique=True, max_length=64)
    project_description = models.JSONField(verbose_name=_('project_description.json'))
    binary = models.FileField(_('firmware file'), null=True, upload_to=firmware_upload_path)

    class Meta:
        unique_together = [
            ('version', 'variant'),
        ]

    @property
    def boards(self):
        return {BoardType[board.board] for board in self.firmwarebuildboard_set.all()
                if board.board in BoardType._member_names_}

    @property
    def chip_type(self) -> ChipType:
        return ChipType(self.chip)

    def serialize(self):
        return {
            'chip': ChipType(self.chip).name,
            'sha256_hash': self.sha256_hash,
            'url': self.binary.url,
            'boards': [board.name for board in self.boards],
        }

    @cached_property
    def firmware_description(self) -> FirmwareDescription:
        return FirmwareDescription(
            chip=self.chip_type,
            project_name=self.version.project_name,
            version=self.version.version,
            idf_version=self.version.idf_version,
            sha256_hash=self.sha256_hash,
            created=self.version.created,
            build=self,
        )

    @cached_property
    def hardware_descriptions(self) -> list[HardwareDescription]:
        return [
            HardwareDescription(
                chip=self.chip_type,
                board=board,
            )
            for board in self.boards
        ]

    @cached_property
    def firmware_image(self) -> FirmwareImage:
        return FirmwareImage.from_file(self.binary.open('rb'))


class FirmwareBuildBoard(models.Model):
    BOARDS = [(boardtype.name, boardtype.pretty_name) for boardtype in BoardType]
    build = models.ForeignKey(FirmwareBuild, on_delete=models.CASCADE)
    board = models.CharField(_('board'), max_length=32, db_index=True, choices=BOARDS)

    class Meta:
        unique_together = [
            ('build', 'board'),
        ]


class OTAUpdate(models.Model):
    build = models.ForeignKey(FirmwareBuild, on_delete=models.CASCADE)
    created = models.DateTimeField(_('creation'), auto_now_add=True)

    @property
    def grouped_recipients(self):
        result = {}
        for recipient in self.recipients.all():
            result.setdefault(recipient.get_status_display(), []).append(recipient)
        return result


class OTARecipientStatus(models.TextChoices):
    RUNNING = "running", _("running")
    REPLACED = "replaced", _("replaced")
    CANCELED = "canceled", _("canceled")
    FAILED = "failed", _("failed")
    SUCCESS = "success", _("success")


class OTAUpdateRecipient(models.Model):
    update = models.ForeignKey(OTAUpdate, on_delete=models.CASCADE, related_name='recipients')
    node = models.ForeignKey(MeshNode, models.PROTECT, related_name='ota_updates',
                             verbose_name=_('node'))
    status = models.CharField(max_length=10, choices=OTARecipientStatus.choices, default=OTARecipientStatus.RUNNING,
                              verbose_name=_('status'))

    class Meta:
        constraints = (
            UniqueConstraint(fields=["node"], condition=Q(status=OTARecipientStatus.RUNNING),
                             name='only_one_active_ota'),
        )

    async def send_status(self):
        """
        use this for OTA stuffs
        """
        await channels.layers.get_channel_layer().group_send(MESH_ALL_OTA_GROUP, self.get_status_json())

    def get_status_json(self):
        return {
            "type": "mesh.ota_recipient_status",
            "node": self.node_id,
            "update": self.update_id,
            "status": self.status,
        }
