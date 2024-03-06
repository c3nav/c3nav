import time
from dataclasses import dataclass
from dataclasses import replace as dataclass_replace
from functools import cached_property
from itertools import chain
from typing import Any, Sequence

import channels
from asgiref.sync import async_to_sync
from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.forms import BooleanField, ChoiceField, Form, ModelMultipleChoiceField, MultipleChoiceField
from django.http import Http404
from django.utils.translation import gettext_lazy as _

from pydantic import ValidationError as PydanticValidationError
from pydantic.type_adapter import TypeAdapter

from c3nav.mesh.baseformats import UnionFormat, get_format
from c3nav.mesh.dataformats import BoardConfig, BoardType, LedType, SerialLedType
from c3nav.mesh.messages import (MESH_BROADCAST_ADDRESS, MESH_ROOT_ADDRESS, MeshMessage, MeshMessageContent,
                                 MeshMessageType)
from c3nav.mesh.models import (FirmwareBuild, HardwareDescription, MeshNode, OTARecipientStatus, OTAUpdate,
                               OTAUpdateRecipient)
from c3nav.mesh.utils import MESH_ALL_OTA_GROUP, group_msg_type_choices


class MeshMessageForm(forms.Form):
    msg_types = {}

    recipients = forms.MultipleChoiceField(choices=())

    def __init__(self, *args, recipient=None, initial=None, **kwargs):
        self.recipient = recipient
        if self.recipient is not None:
            initial = {
                **(initial or {}),
                'recipients': [self.recipient],
            }
        super().__init__(*args, initial=initial, **kwargs)

        recipient_root_choices = {
            MESH_BROADCAST_ADDRESS: _('broadcast')
        }
        node_choices = {
            node.address: str(node) for node in MeshNode.objects.all()
        }
        self.node_choices_flat = {
            **recipient_root_choices,
            **node_choices,
        }
        self.node_choices = tuple(node_choices.items())
        self.node_choices_with_broadcast = (
            *recipient_root_choices.items(),
            (_('nodes'), self.node_choices),
        )

        if self.recipient is None:
            self.fields['recipients'].choices = self.node_choices_with_broadcast
        else:
            if self.recipient not in self.node_choices_flat:
                raise Http404('unknown recipient')
            self.fields.pop('recipients')

    # noinspection PyMethodOverriding
    def __init_subclass__(cls, /, msg=None, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.msg_type in MeshMessageForm.msg_types:
            raise TypeError('duplicate use of msg %s' % cls.msg_type)
        MeshMessageForm.msg_types[cls.msg_type] = cls
        cls.msg_type_class = get_format(MeshMessageContent).models.get(cls.msg_type).model

    @classmethod
    def get_form_for_type(cls, msg_type):
        return cls.msg_types[msg_type]

    def get_recipient_display(self):
        return self.node_choices_flat[self.recipient]

    def get_cleaned_msg_data(self):
        msg_data = self.cleaned_data.copy()
        msg_data.pop('recipients', None)
        return msg_data

    def get_msg_data(self):
        if not self.is_valid():
            raise Exception('nope')

        return {
            "src": MESH_ROOT_ADDRESS,
            "content": {
               "msg_type": self.msg_type.name,
               **self.get_cleaned_msg_data(),
            }
        }

    def get_recipients(self):
        return [self.recipient] if self.recipient else self.cleaned_data['recipients']

    def send(self):
        msg_data = self.get_msg_data()
        recipients = self.get_recipients()
        for recipient in recipients:
            print('sending to ', recipient)
            async_to_sync(MeshMessage.model_validate({
                'dst': recipient,
                **msg_data,
            }).send)()


class MeshRouteRequestForm(MeshMessageForm):
    msg_type = MeshMessageType.MESH_ROUTE_REQUEST

    address = forms.ChoiceField(choices=(), required=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["address"].choices = (('', '------'), )+self.node_choices

    def get_msg_data(self):
        return {
            **super().get_msg_data(),
            "request_id": int(time.time()*100000) % 2**32,
        }


class ConfigUplinkMessageForm(MeshMessageForm):
    msg_type = MeshMessageType.CONFIG_UPLINK

    enabled = forms.BooleanField(required=False, label=_('enabled'))
    ssid = forms.CharField(required=False, label=_('ssid'), max_length=31)
    password = forms.CharField(required=False, label=_('password'), max_length=63)
    channel = forms.IntegerField(min_value=0, max_value=11, label=_('channel'))
    udp = forms.BooleanField(required=False, label=_('udp'))
    ssl = forms.BooleanField(required=False, label=_('ssl'))
    host = forms.CharField(required=False, label=_('host'), max_length=63)
    port = forms.IntegerField(min_value=1, max_value=65535, label=_('port'))


class ConfigBoardMessageForm(MeshMessageForm):
    msg_type = MeshMessageType.CONFIG_BOARD

    board = forms.ChoiceField(choices=((item.name, item.pretty_name) for item in BoardType),
                              label=_('board'))
    led_type = forms.ChoiceField(choices=((item.name, item.pretty_name) for item in LedType),
                                 label=_('LED type'))
    led_serial_type = forms.ChoiceField(choices=((item.name, item.name) for item in SerialLedType),
                                        label=_('serial LED type'), help_text=_('serial LED only'))

    led_serial_gpio = forms.IntegerField(min_value=0, max_value=48, required=False,
                                         label=_('serial LED GPIO pin'), help_text=_('serial LED only'))
    led_multipin_gpio_r = forms.IntegerField(min_value=0, max_value=48, required=False,
                                             label=_('multpin LED GPIO red'), help_text=_('multipin LED only'))
    led_multipin_gpio_g = forms.IntegerField(min_value=0, max_value=48, required=False,
                                             label=_('multpin LED GPIO green'), help_text=_('multipin LED only'))
    led_multipin_gpio_b = forms.IntegerField(min_value=0, max_value=48, required=False,
                                             label=_('multpin LED GPIO blue'), help_text=_('multipin LED only'))

    uwb_enable = forms.BooleanField(required=False, label=_('UWB enable'))
    uwb_gpio_miso = forms.IntegerField(min_value=0, max_value=48, required=False,
                                       label=_('UWB GPIO MISO'), help_text=_('UWB only'))
    uwb_gpio_mosi = forms.IntegerField(min_value=0, max_value=48, required=False,
                                       label=_('UWB GPIO MOSI'), help_text=_('UWB only'))
    uwb_gpio_clk = forms.IntegerField(min_value=0, max_value=48, required=False,
                                      label=_('UWB GPIO CLK'), help_text=_('UWB only'))
    uwb_gpio_cs = forms.IntegerField(min_value=0, max_value=48, required=False,
                                     label=_('UWB GPIO CS'), help_text=_('UWB only'))
    uwb_gpio_irq = forms.IntegerField(min_value=0, max_value=48, required=False,
                                      label=_('UWB GPIO IRQ'), help_text=_('UWB only'))
    uwb_gpio_rst = forms.IntegerField(min_value=-1, max_value=48, required=False,
                                      label=_('UWB GPIO RST'), help_text=_('UWB only'))
    uwb_gpio_wakeup = forms.IntegerField(min_value=-1, max_value=48, required=False,
                                         label=_('UWB GPIO WAKEUP'), help_text=_('UWB only'))
    uwb_gpio_exton = forms.IntegerField(min_value=-1, max_value=48, required=False,
                                        label=_('UWB GPIO EXTON'), help_text=_('UWB only'))

    conditionals = (
        {
            "prefix": "led_",
            "field": "board",
            "values": tuple(
                board_type.name for board_type, cfg_format in get_format(BoardConfig).models.items()
                if "led" in cfg_format._field_formats
            ),
        },
        {
            "prefix": "led_serial_",
            "field": "led_type",
            "values": (LedType.SERIAL.name,),
        },
        {
            "prefix": "led_multipin_",
            "field": "led_type",
            "values": (LedType.MULTIPIN.name,),
        },
        {
            "prefix": "uwb_",
            "field": "board",
            "values": tuple(
                board_type.name for board_type, cfg_format in get_format(BoardConfig).models.items()
                if "uwb" in cfg_format._field_formats
            ),
        },
        {
            "prefix": "uwb_gpio_",
            "field": "uwb_enable",
            "values": (True,)
        },
    )

    def clean(self):
        cleaned_data = super().clean()
        orig_cleaned_keys = set(cleaned_data.keys())

        led_values = {
            "led_type": cleaned_data.pop("led_type"),
            **{
                name.removeprefix('led_'): cleaned_data.pop(name)
                for name in tuple(cleaned_data.keys())
                if name.startswith('led_')
            }
        }
        if led_values:
            cleaned_data["led"] = led_values

        uwb_values = {
            name.removeprefix('uwb_'): cleaned_data.pop(name)
            for name in tuple(cleaned_data.keys())
            if name.startswith('uwb_')
        }
        if uwb_values:
            cleaned_data["uwb"] = uwb_values

        try:
            TypeAdapter(BoardConfig).validate_python(cleaned_data)
        except PydanticValidationError as e:
            from pprint import pprint
            pprint(e.errors())
            errors = {}
            for error in e.errors():
                loc = "_".join(s for s in error["loc"] if not s.isupper())
                if loc in orig_cleaned_keys:
                    errors.setdefault(loc, []).append(error["msg"])
                else:
                    errors.setdefault("__all__", []).append(f"{loc}: {error['msg']}")
            raise ValidationError(errors)

        return cleaned_data


class ConfigPositionMessageForm(MeshMessageForm):
    msg_type = MeshMessageType.CONFIG_POSITION

    x_pos = forms.IntegerField(min_value=0, max_value=2**16-1, label=_('X'))
    y_pos = forms.IntegerField(min_value=0, max_value=2 ** 16 - 1, label=_('Y'))
    z_pos = forms.IntegerField(min_value=0, max_value=2 ** 16 - 1, label=_('Z'))


class LocateRequestRangeMessageForm(MeshMessageForm):
    msg_type = MeshMessageType.LOCATE_REQUEST_RANGE


class EchoRequestMessageForm(MeshMessageForm):
    msg_type = MeshMessageType.ECHO_REQUEST
    content = forms.CharField(max_length=255, label=_('content'))


class OTAApplyMessageForm(MeshMessageForm):
    msg_type = MeshMessageType.OTA_APPLY
    update_id = forms.IntegerField(min_value=0, max_value=2**32-1, label=_('Update ID'))
    reboot = forms.BooleanField(required=False, label=_('reboot'))


class MeshNodeForm(forms.ModelForm):
    class Meta:
        model = MeshNode
        fields = ["name"]


class RangingForm(forms.Form):
    msg_types = {}

    range_from = forms.MultipleChoiceField(choices=(), required=True)
    range_to = forms.MultipleChoiceField(choices=(), required=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        node_choices = tuple((node.address, str(node)) for node in MeshNode.objects.all())
        self.fields['range_from'].choices = node_choices
        self.fields['range_to'].choices = node_choices


@dataclass
class OTAFormGroup:
    hardware: HardwareDescription
    builds: Sequence[FirmwareBuild]
    fields: dict[str, tuple[MeshNode, Any]]

    @cached_property
    def builds_by_id(self) -> dict[int, FirmwareBuild]:
        return {build.pk: build for build in self.builds}


class OTACreateForm(Form):
    def __init__(self, builds: Sequence[FirmwareBuild], *args, **kwargs):
        super().__init__(*args, **kwargs)

        nodes: Sequence[MeshNode] = MeshNode.objects.prefetch_last_messages(
            MeshMessageType.CONFIG_BOARD
        ).prefetch_firmwares().prefetch_ota()

        builds_by_hardware = {}
        for build in builds:
            for hardware_desc in build.hardware_descriptions:
                builds_by_hardware.setdefault(hardware_desc, []).append(build)

        nodes_by_hardware = {}
        for node in nodes:
            nodes_by_hardware.setdefault(node.hardware_description, []).append(node)

        self._groups: list[OTAFormGroup] = []
        for hardware, hw_nodes in sorted(nodes_by_hardware.items(), key=lambda k: len(k[1]), reverse=True):
            try:
                hw_builds = builds_by_hardware[hardware]
            except KeyError:
                continue
            choices = [
                ('', '---'),
                *((build.pk, build.variant) for build in hw_builds)
            ]

            group = OTAFormGroup(
                hardware=hardware,
                builds=hw_builds,
                fields={
                    f'build_{node.pk}': (node, (
                        ChoiceField(choices=choices, required=False)
                        if len(hw_builds) > 1
                        else BooleanField(required=False)
                    )) for node in hw_nodes
                }
            )
            for name, (node, hw_field) in group.fields.items():
                self.fields[name] = hw_field
            self._groups.append(group)

    @property
    def groups(self) -> list[OTAFormGroup]:
        return [
            dataclass_replace(group, fields={
                name: (node, self[name])
                for name, (node, hw_field) in group.fields.items()
            })
            for group in self._groups
        ]

    @property
    def selected_builds(self):
        build_nodes = {}
        for group in self._groups:
            for name, (node, hw_field) in group.fields.items():
                value = self.cleaned_data.get(name, None)
                if not value:
                    continue
                if len(group.builds) == 1:
                    build_nodes.setdefault(group.builds[0], []).append(node)
                else:
                    build_nodes.setdefault(group.builds[0], []).append(group.builds_by_id[int(value)])
        return build_nodes

    def save(self) -> list[OTAUpdate]:
        updates = []
        addresses = []
        with transaction.atomic():
            replaced_recipients = OTAUpdateRecipient.objects.filter(
                node__in=chain(*self.selected_builds.values()),
                status=OTARecipientStatus.RUNNING,
            ).select_for_update()
            replaced_recipients.update(status=OTARecipientStatus.REPLACED)
            for build, nodes in self.selected_builds.items():
                update = OTAUpdate.objects.create(build=build)
                for node in nodes:
                    update.recipients.create(node=node)
                    addresses.append(node.address)
                updates.append(update)
        async_to_sync(channels.layers.get_channel_layer().group_send)(MESH_ALL_OTA_GROUP, {
            "type": "mesh.ota_recipients_changed",
            "addresses": addresses,
        })
        return updates


class MeshMessageFilterForm(Form):
    message_types = MultipleChoiceField(
        choices=group_msg_type_choices(list(MeshMessageType)),
        required=False,
        label=_('message types'),
    )
    src_nodes = ModelMultipleChoiceField(
        queryset=MeshNode.objects.all(),
        required=False,
        label=_('nodes'),
    )
