from django.views.generic import DetailView, ListView, TemplateView

from c3nav.mesh.messages import MeshMessageType
from c3nav.mesh.models import FirmwareBuild, FirmwareVersion, MeshNode
from c3nav.mesh.views.base import MeshControlMixin


class FirmwaresListView(MeshControlMixin, ListView):
    model = FirmwareVersion
    template_name = "mesh/firmwares.html"
    ordering = "-created"
    context_object_name = "firmwares"
    paginate_by = 20


class FirmwaresCurrentListView(MeshControlMixin, TemplateView):
    template_name = "mesh/firmwares_current.html"

    def get_context_data(self, **kwargs):
        nodes = list(MeshNode.objects.all().prefetch_firmwares())

        firmwares = {}
        for node in nodes:
            firmwares.setdefault(node.firmware_desc.get_lookup(), (node.firmware_desc, []))[1].append(node)

        firmwares = sorted(firmwares.values(), key=lambda k: k[0].created, reverse=True)

        print(firmwares)

        return {
            **super().get_context_data(),
            "firmwares": firmwares,
        }


class FirmwareDetailView(MeshControlMixin, DetailView):
    model = FirmwareVersion
    template_name = "mesh/firmware_detail.html"
    context_object_name = "firmware"

    def get_queryset(self):
        return super().get_queryset().prefetch_related('builds', 'builds__firmwarebuildboard_set')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data()

        nodes = list(MeshNode.objects.all().prefetch_firmwares().prefetch_last_messages(
            MeshMessageType.CONFIG_BOARD,
        ))
        builds = self.get_object().builds.all()

        build_lookups = set(build.get_firmware_description().get_lookup() for build in builds)

        installed_nodes = []
        compatible_nodes = []
        for node in nodes:
            if node.firmware_desc.get_lookup() in build_lookups:
                installed_nodes.append(node)
            else:
                node.compatible_builds = []
                for build in builds:
                    if node.board in build.boards:
                        node.compatible_builds.append(build)
                if node.compatible_builds:
                    compatible_nodes.append(node)

        ctx.update({
            'builds': builds,
            'installed_nodes': installed_nodes,
            'compatible_nodes': compatible_nodes,
        })
        return ctx


class FirmwareBuildDetailView(MeshControlMixin, DetailView):
    model = FirmwareBuild
    template_name = "mesh/firmware_build_detail.html"
    context_object_name = "build"

    def get_queryset(self):
        return super().get_queryset().prefetch_related('firmwarebuildboard_set')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data()

        nodes = list(MeshNode.objects.all().prefetch_firmwares().prefetch_last_messages(
            MeshMessageType.CONFIG_BOARD,
        ))

        build_lookup = self.get_object().get_firmware_description().get_lookup()
        build_boards = self.get_object().boards

        installed_nodes = []
        compatible_nodes = []
        for node in nodes:
            if node.firmware_desc.get_lookup() == build_lookup:
                installed_nodes.append(node)
            else:
                if node.board in build_boards:
                    compatible_nodes.append(node)

        ctx.update({
            'installed_nodes': installed_nodes,
            'compatible_nodes': compatible_nodes,
        })
        return ctx
