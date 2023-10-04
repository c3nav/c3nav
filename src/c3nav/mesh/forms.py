from django import forms
from django.http import Http404
from django.utils.translation import gettext_lazy as _

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

    def send(self):
        if not self.is_valid():
            raise Exception('nope')

        msg_data = {
            'msg_id': self.msg_type,
            'src': ROOT_ADDRESS,
            **self.cleaned_data,
        }

        recipients = [self.recipient] if self.recipient else self.cleaned_data['recipients']
        for recipient in recipients:
            print('sending to ', recipient)
            MeshMessage.fromjson({
                'dst': recipient,
                **msg_data,
            }).send()
