from dataclasses import fields as dataclass_fields

from django import forms
from django.core.exceptions import ValidationError
from django.http import Http404
from django.utils.translation import gettext_lazy as _

from c3nav.mesh.dataformats import LedConfig
from c3nav.mesh.messages import MeshMessageType, MeshMessage, ROOT_ADDRESS
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
            'ff:ff:ff:ff:ff:ff': _('broadcast')
        }
        recipient_node_choices = {
            node.address: str(node) for node in MeshNode.objects.all()
        }
        self.recipient_choices = {
            **recipient_root_choices,
            **recipient_node_choices,
        }
        if self.recipient is None:
            self.fields['recipients'].choices = (
                *recipient_root_choices.items(),
                (_('nodes'), tuple(recipient_node_choices.items()))
            )
        else:
            if self.recipient not in self.recipient_choices:
                raise Http404
            self.fields.pop('recipients')

    # noinspection PyMethodOverriding
    def __init_subclass__(cls, /, msg=None, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.msg_type in MeshMessageForm.msg_types:
            raise TypeError('duplicate use of msg %s' % cls.msg_type)
        MeshMessageForm.msg_types[cls.msg_type] = cls

    @classmethod
    def get_form_for_type(cls, msg_type):
        return cls.msg_types[msg_type]

    def get_recipient_display(self):
        return self.recipient_choices[self.recipient]

    def get_cleaned_msg_data(self):
        msg_data = self.cleaned_data.copy()
        msg_data.pop('recipients', None)
        return msg_data

    def get_msg_data(self):
        if not self.is_valid():
            raise Exception('nope')

        return {
            'msg_id': self.msg_type,
            'src': ROOT_ADDRESS,
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


class ConfigLedMessageForm(MeshMessageForm):
    msg_type = MeshMessageType.CONFIG_LED

    led_type = forms.ChoiceField(choices=(
        ('', _('no LED')),
        (1, _('serial LED')),
        (2, _('multipin LED'))
    ))
    gpio = forms.IntegerField(min_value=0, max_value=48, required=False,
                              label=_('gpio pin'), help_text=_('serial only'))
    rmt = forms.IntegerField(min_value=0, max_value=7, required=False,
                             label=_('rmt'), help_text=_('serial only'))
    gpio_r = forms.IntegerField(min_value=0, max_value=48, required=False,
                                label=_('gpio red'), help_text=_('multipin only'))
    gpio_g = forms.IntegerField(min_value=0, max_value=48, required=False,
                                label=_('gpio green'), help_text=_('multipin only'))
    gpio_b = forms.IntegerField(min_value=0, max_value=48, required=False,
                                label=_('gpio blue'), help_text=_('multipin only'))

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

        for key, value in cleaned_data.items():
            if key == "recipients":
                continue
            if value and key not in required_fields:
                errors[key] = _("this field is not allowed for this LED type")

        for key in required_fields:
            value = cleaned_data.pop(key, "")
            if value == "":
                errors[key] = _("this field is required for this LED type")
            led_config[key] = value

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