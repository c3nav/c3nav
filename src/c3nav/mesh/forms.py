import time

from asgiref.sync import async_to_sync
from django import forms
from django.core.exceptions import ValidationError
from django.http import Http404
from django.utils.translation import gettext_lazy as _

from c3nav.mesh.dataformats import BoardConfig, BoardType, LedType, SerialLedType
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
            'msg_type': self.msg_type.name,
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
            async_to_sync(MeshMessage.fromjson({
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
                cfg.board.name for cfg in BoardConfig._union_options["board"].values()
                if "led" in cfg.__dataclass_fields__
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
                cfg.board.name for cfg in BoardConfig._union_options["board"].values()
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

        board_cfg = BoardConfig._union_options["board"][BoardType[cleaned_data["board"]]]
        has_led = "led" in board_cfg.__dataclass_fields__
        has_uwb = "uwb" in board_cfg.__dataclass_fields__

        led_values = {
            "led_type": cleaned_data.pop("led_type"),
            **{
                name.removeprefix('led_'): cleaned_data.pop(name)
                for name in tuple(cleaned_data.keys())
                if name.startswith('led_')
            }
        }
        uwb_values = {
            name.removeprefix('uwb_'): cleaned_data.pop(name)
            for name in tuple(cleaned_data.keys())
            if name.startswith('uwb_')
        }

        errors = {}

        if has_led:
            prefix = led_values["led_type"].lower()+'_'
            cleaned_data["led"] = {
                "led_type": led_values["led_type"],
                **{
                    name.removeprefix(prefix): value
                    for name, value in led_values.items()
                    if name.startswith(prefix)
                }
            }
            for key, value in tuple(cleaned_data["led"].items()):
                if value is None:
                    field_name = f'led_{prefix}{key}'
                    if self.fields[field_name].min_value == -1:
                        cleaned_data[key] = -1
                    else:
                        errors[field_name] = _('this field is required')

        if has_uwb:
            cleaned_data["uwb"] = uwb_values
            for key, value in tuple(cleaned_data["uwb"].items()):
                if value is None:
                    field_name = f'uwb_{key}'
                    if self.fields[field_name].min_value == -1 or not cleaned_data["uwb"]["enable"]:
                        cleaned_data[key] = -1
                    else:
                        errors[field_name] = _('this field is required')

        if errors:
            raise ValidationError(errors)

        return cleaned_data


class ConfigPositionMessageForm(MeshMessageForm):
    msg_type = MeshMessageType.CONFIG_POSITION

    x_pos = forms.IntegerField(min_value=0, max_value=2**16-1, label=_('X'))
    y_pos = forms.IntegerField(min_value=0, max_value=2 ** 16 - 1, label=_('Y'))
    z_pos = forms.IntegerField(min_value=0, max_value=2 ** 16 - 1, label=_('Z'))


class LocateRequestRangeMessageForm(MeshMessageForm):
    msg_type = MeshMessageType.LOCATE_REQUEST_RANGE


class MeshNodeForm(forms.ModelForm):
    class Meta:
        model = MeshNode
        fields = ["name"]
