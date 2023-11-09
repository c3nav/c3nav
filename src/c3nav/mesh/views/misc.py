from django.views.generic import TemplateView

from c3nav.mesh.utils import get_node_names
from c3nav.mesh.views.base import MeshControlMixin


class MeshLogView(MeshControlMixin, TemplateView):
    template_name = "mesh/mesh_logs.html"

    def get_context_data(self, **kwargs):
        return {
            **super().get_context_data(),
            "node_names": get_node_names(),
        }
