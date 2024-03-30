from django.views.generic import DetailView, ListView

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

