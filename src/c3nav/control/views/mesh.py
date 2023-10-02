from django.views.generic import ListView

from c3nav.control.views.base import ControlPanelMixin
from c3nav.mesh.models import MeshNode


class MeshNodeListView(ControlPanelMixin, ListView):
    model = MeshNode
    template_name = "control/mesh_nodes.html"
    ordering = "address"
    context_object_name = "nodes"
