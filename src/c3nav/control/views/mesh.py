from django.db.models import Max
from django.views.generic import ListView, DetailView

from c3nav.control.forms import MeshMessageFilerForm
from c3nav.control.views.base import ControlPanelMixin
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


class MeshMessageListView(ControlPanelMixin, ListView):
    model = NodeMessage
    template_name = "control/mesh_messages.html"
    ordering = "-datetime"
    paginate_by = 20
    context_object_name = "mesh_messages"

    def get_queryset(self):
        qs = super().get_queryset()

        self.form = MeshMessageFilerForm(self.request.GET)
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
