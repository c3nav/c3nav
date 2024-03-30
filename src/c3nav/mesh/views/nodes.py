from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, ListView, UpdateView

from c3nav.mesh.forms import MeshNodeForm
from c3nav.mesh.models import MeshNode
from c3nav.mesh.views.base import MeshControlMixin


class NodeListView(MeshControlMixin, ListView):
    model = MeshNode
    template_name = "mesh/nodes.html"
    ordering = "address"
    context_object_name = "nodes"

    def get_queryset(self):
        return (super().get_queryset().prefetch_last_messages().prefetch_firmwares()
                .prefetch_ranging_beacon().select_related("upstream"))


class NodeDetailView(MeshControlMixin, DetailView):
    model = MeshNode
    template_name = "mesh/node_detail.html"
    pk_url_kwargs = "address"
    context_object_name = "node"

    def get_queryset(self):
        return super().get_queryset().prefetch_last_messages().prefetch_firmwares().select_related("upstream")


class NodeEditView(MeshControlMixin, SuccessMessageMixin, UpdateView):
    model = MeshNode
    form_class = MeshNodeForm
    template_name = "control/form.html"
    success_message = _('Name updated successfully')

    def get_context_data(self, **kwargs):
        return {
            **super().get_context_data(),
            'title': _('Editing mesh node: %s') % self.get_object(),
        }

    def get_success_url(self):
        return reverse('mesh.node.detail', kwargs={'pk': self.get_object().pk})
