from functools import cached_property
from uuid import uuid4

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import FormView, ListView, TemplateView

from c3nav.mesh.forms import MeshMessageFilterForm, MeshMessageForm
from c3nav.mesh.messages import MeshMessage, MeshMessageType
from c3nav.mesh.models import MeshNode, NodeMessage
from c3nav.mesh.utils import get_node_names, group_msg_type_choices
from c3nav.mesh.views.base import MeshControlMixin


class MeshMessageListView(MeshControlMixin, ListView):
    model = NodeMessage
    template_name = "mesh/mesh_messages.html"
    ordering = "-datetime"
    paginate_by = 20
    context_object_name = "mesh_messages"

    def get_queryset(self):
        qs = super().get_queryset()

        self.form = MeshMessageFilterForm(self.request.GET)
        if self.form.is_valid():
            if self.form.cleaned_data['message_types']:
                qs = qs.filter(message_type__in=self.form.cleaned_data['message_types'])
            if self.form.cleaned_data['src_nodes']:
                qs = qs.filter(src_node__in=self.form.cleaned_data['src_nodes'])

        return qs

    def get_context_data(self, *args, **kwargs):
        ctx = super().get_context_data(*args, **kwargs)

        form_data = self.request.GET.copy()
        form_data.pop('page', None)

        ctx.update({
            "node_names": get_node_names(),
            "send_msg_types": group_msg_type_choices({msg_type for msg_type in MeshMessageForm.msg_types.keys()}),
            'form': self.form,
            'form_data': form_data.urlencode(),
        })
        return ctx

    def post(self, request):
        return redirect(
            reverse("mesh.send", kwargs={"msg_type": request.POST.get("send_msg_type", "")})
        )


class MeshMessageSendView(MeshControlMixin, FormView):
    template_name = "mesh/mesh_message_send.html"

    @cached_property
    def msg_type(self):
        return MeshMessageType[self.kwargs['msg_type']]

    def get_form_class(self):
        try:
            return MeshMessageForm.get_form_for_type(self.msg_type)
        except KeyError:
            raise Http404('unknown message type')

    def get_form_kwargs(self):
        return {
            **super().get_form_kwargs(),
            'recipient': self.kwargs.get('recipient', None),
        }

    def get_initial(self):
        if 'recipient' in self.kwargs and self.msg_type.name.startswith('CONFIG_'):
            try:
                node = MeshNode.objects.get(address=self.kwargs['recipient'])
            except MeshNode.DoesNotExist:
                pass
            else:
                initial = node.last_messages[self.msg_type].parsed.content.model_dump(mode="json")
                while keys := tuple(key for key, value in initial.items() if isinstance(value, dict)):
                    for key in keys:
                        subdict = initial.pop(key)
                        for subkey, value in subdict.items():
                            initial[key+"_"+subkey.removeprefix(key).lstrip('_')] = value
                return initial

        if 'address' in self.request.GET and self.msg_type == MeshMessageType.MESH_ROUTE_REQUEST:
            return {"address": self.request.GET["address"]}

        return {}

    def get_success_url(self):
        if 'recipient' in self.kwargs and False:
            return reverse('mesh.node.detail', kwargs={'pk': self.kwargs['recipient']})
        else:
            return self.request.path

    def form_valid(self, form):
        if 'noscript' in self.request.POST:
            form.send()
            messages.success(self.request, _('Message sent successfully(?)'))
            return super().form_valid(form)
        uuid = uuid4()
        self.request.session["mesh_msg_%s" % uuid] = {
            "success_url": self.get_success_url(),
            "recipients": form.get_recipients(),
            "msg_data": form.get_msg_data(),
        }
        return redirect(reverse('mesh.sending', kwargs={'uuid': uuid}))


class MeshMessageSendingView(MeshControlMixin, TemplateView):
    template_name = "mesh/mesh_message_sending.html"

    def get_context_data(self, uuid):
        try:
            data = self.request.session["mesh_msg_%s" % uuid]
        except KeyError:
            raise Http404
        node_names = get_node_names()
        return {
            **super().get_context_data(),
            "node_names": node_names,
            "send_uuid": uuid,
            **data,
            "node_name": node_names.get(data["msg_data"]["content"].get("address"), ""),
            "recipients": [(address, node_names[address]) for address in data["recipients"]],
            "msg_type": MeshMessageType[data["msg_data"]["content"]["msg_type"]].pretty_name,
            "msg_type_raw": MeshMessageType[data["msg_data"]["content"]["msg_type"]],
        }
