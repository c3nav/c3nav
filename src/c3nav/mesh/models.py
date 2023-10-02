from django.db import models
from django.utils.translation import gettext_lazy as _

from c3nav.mesh.messages import MessageType


class ChipID(models.IntegerChoices):
    ESP32S2 = 2, 'ESP32-S2'
    ESP32C3 = 5, 'ESP32-C3'


class MeshNode(models.Model):
    address = models.CharField(_('mac address'), max_length=17, primary_key=True)
    name = models.CharField(_('name'), max_length=32, null=True, blank=True)
    first_seen = models.DateTimeField(_('first seen'), auto_now_add=True)
    parent_node = models.ForeignKey('MeshNode', models.PROTECT, null=True,
                                    related_name='child_nodes', verbose_name=_('parent node'))
    route = models.ForeignKey('MeshNode', models.PROTECT, null=True,
                              related_name='routed_nodes', verbose_name=_('route'))
    firmware = models.ForeignKey('Firmware', models.PROTECT, null=True,
                                 related_name='installed_on', verbose_name=_('firmware'))

    def __str__(self):
        if self.name:
            return '%s (%s)' % (self.address, self.name)
        return self.address


class NodeMessage(models.Model):
    MESSAGE_TYPES = [(msgtype.value, msgtype.name) for msgtype in MessageType]
    node = models.ForeignKey('MeshNode', models.PROTECT, null=True,
                             related_name='received_messages', verbose_name=_('node'))
    datetime = models.DateTimeField(_('datetime'), db_index=True, auto_now_add=True)
    message_type = models.SmallIntegerField(_('message type'), db_index=True, choices=MESSAGE_TYPES)
    data = models.JSONField(_('message data'))

    def __str__(self):
        return '(#%d) %s at %s' % (self.pk, self.get_message_type_display(), self.datetime)


class Firmware(models.Model):
    chip = models.SmallIntegerField(_('chip'), db_index=True, choices=ChipID.choices)
    project_name = models.CharField(_('project name'), max_length=32)
    version = models.CharField(_('firmware version'), max_length=32)
    idf_version = models.CharField(_('IDF version'), max_length=32)
    sha256_hash = models.CharField(_('SHA256 hash'), unique=True, max_length=64)
    binary = models.FileField(_('firmware file'), null=True)

    class Meta:
        unique_together = [
            ('chip', 'project_name', 'version', 'idf_version', 'sha256_hash'),
        ]
