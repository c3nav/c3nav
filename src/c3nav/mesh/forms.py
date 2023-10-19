import time
from dataclasses import fields as dataclass_fields

from django import forms
from django.core.exceptions import ValidationError
from django.http import Http404
from django.utils.translation import gettext_lazy as _

from c3nav.mesh.dataformats import LedConfig, LedType, SerialLedType, BoardType, BoardConfig
from c3nav.mesh.messages import MESH_BROADCAST_ADDRESS, MESH_ROOT_ADDRESS, MeshMessage, MeshMessageType
from c3nav.mesh.models import MeshNode


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
        cls.msg_type_class = MeshMessage.get_type(cls.msg_type)

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
            'msg_id': self.msg_type,
            'src': MESH_ROOT_ADDRESS,
            **self.get_cleaned_msg_data(),
        }

    def get_recipients(self):
        return [self.recipient] if self.recipient else self.cleaned_data['recipients']

    def send(self):
        msg_data = self.get_msg_data()
        recipients = self.get_recipients()
        for recipient in recipients:
            print('sending to ', recipient)
            MeshMessage.fromjson({
                'dst': recipient,
                **msg_data,
            }).send()


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

    # todo: don't use numerical values
    board = forms.ChoiceField(choices=((item.value, item.name) for item in BoardType),
                              label=_('board'))
    led_type = forms.ChoiceField(choices=((item.value, item.name) for item in LedType),
                                 label=_('LED type'))
    led_serial_type = forms.ChoiceField(choices=((item.value or '', item.name) for item in SerialLedType),
                                        label=_('serial LED type'), help_text=_('serial LED only'))
    # todo: make this use the modern messages
    led_serial_gpio = forms.IntegerField(min_value=0, max_value=48, required=False,
                                         label=_('serial LED GPIO pin'), help_text=_('serial LED only'))
    led_multipin_gpio_r = forms.IntegerField(min_value=0, max_value=48, required=False,
                                             label=_('multpin LED GPIO red'), help_text=_('multipin LED only'))
    led_multipin_gpio_g = forms.IntegerField(min_value=0, max_value=48, required=False,
                                             label=_('multpin LED GPIO green'), help_text=_('multipin LED only'))
    led_multipin_gpio_b = forms.IntegerField(min_value=0, max_value=48, required=False,
                                             label=_('multpin LED GPIO blue'), help_text=_('multipin LED only'))

    uwb_enable = forms.BooleanField(required=False, label=_('UWB enable'))
    uwb_gpio_miso = forms.IntegerField(min_value=-1, max_value=48, required=False,
                                       label=_('UWB GPIO MISO'), help_text=_('UWB only'))
    uwb_gpio_mosi = forms.IntegerField(min_value=-1, max_value=48, required=False,
                                       label=_('UWB GPIO MOSI'), help_text=_('UWB only'))
    uwb_gpio_clk = forms.IntegerField(min_value=-1, max_value=48, required=False,
                                      label=_('UWB GPIO CLK'), help_text=_('UWB only'))
    uwb_gpio_cs = forms.IntegerField(min_value=-1, max_value=48, required=False,
                                     label=_('UWB GPIO CS'), help_text=_('UWB only'))
    uwb_gpio_irq = forms.IntegerField(min_value=-1, max_value=48, required=False,
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
                str(cfg.board.value) for cfg in BoardConfig._union_options["board"].values()
                if "led" in cfg.__dataclass_fields__
            ),
        },
        {
            "prefix": "led_serial_",
            "field": "led_type",
            "values": (str(LedType.SERIAL.value),),
        },
        {
            "prefix": "led_multipin_",
            "field": "led_type",
            "values": (str(LedType.MULTIPIN.value),),
        },
        {
            "prefix": "uwb_",
            "field": "board",
            "values": tuple(
                str(cfg.board.value) for cfg in BoardConfig._union_options["board"].values()
                if "uwb" in cfg.__dataclass_fields__
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

        led_type = int(cleaned_data["led_type"])

        if led_type:
            required_fields = set(field.name for field in dataclass_fields(LedConfig.ledconfig_types[led_type]))
        else:
            required_fields = set()

        errors = {}
        led_config = {
            "led_type": led_type
        }

        """for key, value in cleaned_data.items():
            if key == "recipients":
                continue
            if value and key not in required_fields:
                errors[key] = _("this field is not allowed for this LED type")

        for key in required_fields:
            value = cleaned_data.pop(key, "")
            if value == "":
                errors[key] = _("this field is required for this LED type")
            led_config[key] = value"""

        cleaned_data["led_config"] = led_config

        if errors:
            raise ValidationError(errors)

        return cleaned_data

    def get_cleaned_msg_data(self):
        msg_data = super().get_cleaned_msg_data().copy()
        msg_data = {
            "led_config": msg_data["led_config"],
        }
        return msg_data

    def __init__(self, *args, initial=None, **kwargs):
        if initial:
            initial.update(initial.pop('led_config'))
        super().__init__(*args, initial=initial, **kwargs)


class ConfigPositionMessageForm(MeshMessageForm):
    msg_type = MeshMessageType.CONFIG_POSITION

    x_pos = forms.IntegerField(min_value=0, max_value=2**16-1, label=_('X'))
    y_pos = forms.IntegerField(min_value=0, max_value=2 ** 16 - 1, label=_('Y'))
    z_pos = forms.IntegerField(min_value=0, max_value=2 ** 16 - 1, label=_('Z'))


class MeshNodeForm(forms.ModelForm):
    class Meta:
        model = MeshNode
        fields = ["name"]
