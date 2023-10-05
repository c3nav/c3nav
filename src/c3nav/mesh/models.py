from collections import UserDict
from functools import cached_property
from operator import attrgetter
from typing import Mapping, Self, Any

from django.db import models, NotSupportedError
from django.utils.translation import gettext_lazy as _

from c3nav.mesh.messages import MeshMessageType, ChipType, MeshMessage as MeshMessage


class MeshNodeQuerySet(models.QuerySet):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._prefetch_last_messages = set()
        self._prefetch_last_messages_done = False

    def _clone(self):
        clone = super()._clone()
        clone._prefetch_last_messages = self._prefetch_last_messages
        return clone

    def prefetch_last_messages(self, *types: MeshMessageType):
        clone = self._chain()
        clone._prefetch_last_messages |= (
            set(types) if types else set(msgtype.value for msgtype in MeshMessageType)
        )
        return clone

    def _fetch_all(self):
        super()._fetch_all()
        if self._prefetch_last_messages and not self._prefetch_last_messages_done:
            nodes = {node.pk: node for node in self._result_cache}
            try:
                for message in NodeMessage.objects.order_by('-datetime', '-pk').filter(
                        message_type__in=self._prefetch_last_messages,
                        src_node__in=nodes.keys(),
                ).prefetch_related("uplink_node").distinct('message_type', 'src_node'):
                    nodes[message.node].last_messages[message.message_type] = message
                for node in nodes.values():
                    node.last_messages["any"] = max(node.last_messages.values(), key=attrgetter("datetime"))
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
        msg = self.node.received_messages.filter(message_type=key).order_by('-datetime', '-pk').first()
        self.data[key] = msg
        return msg

    def __setitem__(self, key, item):
        self.data[self._get_key(key)] = item


class MeshNode(models.Model):
    address = models.CharField(_('mac address'), max_length=17, primary_key=True)
    name = models.CharField(_('name'), max_length=32, null=True, blank=True)
    first_seen = models.DateTimeField(_('first seen'), auto_now_add=True)
    uplink = models.ForeignKey('MeshNode', models.PROTECT, null=True,
                               related_name='routed_nodes', verbose_name=_('uplink'))
    last_signin = models.DateTimeField(_('last signin'), null=True)
    objects = models.Manager.from_queryset(MeshNodeQuerySet)()

    def __str__(self):
        if self.name:
            return '%s (%s)' % (self.address, self.name)
        return self.address

    @cached_property
    def last_messages(self) -> Mapping[Any, Self]:
        return LastMessagesByTypeLookup(self)


class NodeMessage(models.Model):
    MESSAGE_TYPES = [(msgtype.value, msgtype.name) for msgtype in MeshMessageType]
    src_node = models.ForeignKey('MeshNode', models.PROTECT,
                                 related_name='received_messages', verbose_name=_('node'))
    uplink_node = models.ForeignKey('MeshNode', models.PROTECT,
                                    related_name='relayed_messages', verbose_name=_('uplink node'))
    datetime = models.DateTimeField(_('datetime'), db_index=True, auto_now_add=True)
    message_type = models.SmallIntegerField(_('message type'), db_index=True, choices=MESSAGE_TYPES)
    data = models.JSONField(_('message data'))

    def __str__(self):
        return '(#%d) %s at %s' % (self.pk, self.get_message_type_display(), self.datetime)

    @cached_property
    def parsed(self) -> dict:
        return MeshMessage.fromjson(self.data)


class Firmware(models.Model):
    CHIPS = [(msgtype.value, msgtype.name.replace('_', '-')) for msgtype in ChipType]
    chip = models.SmallIntegerField(_('chip'), db_index=True, choices=CHIPS)
    project_name = models.CharField(_('project name'), max_length=32)
    version = models.CharField(_('firmware version'), max_length=32)
    idf_version = models.CharField(_('IDF version'), max_length=32)
    sha256_hash = models.CharField(_('SHA256 hash'), unique=True, max_length=64)
    binary = models.FileField(_('firmware file'), null=True)

    class Meta:
        unique_together = [
            ('chip', 'project_name', 'version', 'idf_version', 'sha256_hash'),
        ]
