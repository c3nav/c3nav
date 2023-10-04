from django.contrib import messages
from django.db.models import Max
from django.http import Http404
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import ListView, DetailView, FormView

from c3nav.control.forms import MeshMessageFilterForm
from c3nav.control.views.base import ControlPanelMixin
from c3nav.mesh.forms import MeshMessageForm
from c3nav.mesh.messages import MessageType
from c3nav.mesh.models import MeshNode, NodeMessage


class MeshNodeListView(ControlPanelMixin, ListView):
    model = MeshNode
    template_name = "control/mesh_nodes.html"
    ordering = "address"
    context_object_name = "nodes"

    def get_queryset(self):
        return super().get_queryset().annotate(last_msg=Max('received_messages__datetime')).prefetch_last_messages()


class MeshNodeDetailView(ControlPanelMixin, DetailView):
    model = MeshNode
    template_name = "control/mesh_node_detail.html"
    pk_url_kwargs = "address"
    context_object_name = "node"

    def get_queryset(self):
        return super().get_queryset().annotate(last_msg=Max('received_messages__datetime')).prefetch_last_messages()


class MeshMessageListView(ControlPanelMixin, ListView):
    model = NodeMessage
    template_name = "control/mesh_messages.html"
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
            'form': self.form,
            'form_data': form_data.urlencode(),
        })
        return ctx


class MeshMessageSendView(ControlPanelMixin, FormView):
    template_name = "control/mesh_message_send.html"

    def get_form_class(self):
        try:
            return MeshMessageForm.get_form_for_type(MessageType[self.kwargs['msg_type']])
        except KeyError:
            raise Http404('unknown message type')

    def get_form_kwargs(self):
        return {
            **super().get_form_kwargs(),
            'recipient': self.kwargs.get('recipient', None),
        }

    def get_initial(self):
        if 'recipient' in self.kwargs and self.kwargs['msg_type'].startswith('CONFIG_'):
            try:
                node = MeshNode.objects.get(address=self.kwargs['recipient'])
            except MeshNode.DoesNotExist:
                pass
            else:
                return node.last_messages[self.kwargs['msg_type']].parsed.tojson()
        return {}

    def get_success_url(self):
        if 'recipient' in self.kwargs and False:
            return reverse('control.mesh_node.detail', kwargs={'pk': self.kwargs['recipient']})
        else:
            return self.request.path

    def form_valid(self, form):
        form.send()
        messages.success(self.request, _('Message sent successfully'))
        return super().form_valid(form)
