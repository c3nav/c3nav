from django.views.generic import TemplateView

from c3nav.mesh.forms import RangingForm
from c3nav.mesh.utils import get_node_names
from c3nav.mesh.views.base import MeshControlMixin


class MeshLogView(MeshControlMixin, TemplateView):
    template_name = "mesh/mesh_logs.html"

    def get_context_data(self, **kwargs):
        return {
            **super().get_context_data(),
            "node_names": get_node_names(),
        }


class MeshRangingView(TemplateView):
    template_name = "mesh/mesh_ranging.html"

    def get_context_data(self, **kwargs):
        from c3nav.routing.locator import Locator
        return {
            "ranging_form": RangingForm(self.request.GET or None),
            "node_names": get_node_names(),
            "nodes_xyz": Locator.load().get_all_nodes_xyz(),
        }
