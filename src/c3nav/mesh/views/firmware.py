from django.contrib.messages.views import SuccessMessageMixin
from django.views.generic import DetailView, ListView, TemplateView
from django.views.generic.edit import FormMixin

from c3nav.mesh.forms import OTACreateForm
from c3nav.mesh.models import FirmwareBuild, FirmwareVersion, MeshNode, OTARecipientStatus, OTAUpdate
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
            firmwares.setdefault(
                node.firmware_description.get_lookup(), (node.firmware_description, [])
            )[1].append(node)

        firmwares = sorted(firmwares.values(), key=lambda k: k[0].created, reverse=True)

        print(firmwares)

        return {
            **super().get_context_data(),
            "firmwares": firmwares,
        }


class OTACreateMixin(SuccessMessageMixin, MeshControlMixin, FormMixin):
    form_class = OTACreateForm
    success_message = 'OTA have been created'

    def post(self, *args, **kwargs):
        form = self.get_form()
        if not form.is_valid():
            return self.form_invalid(form)
        form.save()
        return self.form_valid(form)

    def get_success_url(self):
        return self.request.path


class FirmwareDetailView(OTACreateMixin, MeshControlMixin, DetailView):
    model = FirmwareVersion
    template_name = "mesh/firmware_detail.html"
    context_object_name = "firmware"

    def get_queryset(self):
        return super().get_queryset().prefetch_related('builds', 'builds__firmwarebuildboard_set')

    def get_form_kwargs(self):
        return {
            **super().get_form_kwargs(),
            'builds': self.get_object().builds.all(),
        }

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data()
        ctx.update({
            'builds': self.get_object().builds.all(),
        })
        return ctx


class FirmwareBuildDetailView(OTACreateMixin, MeshControlMixin, DetailView):
    model = FirmwareBuild
    template_name = "mesh/firmware_build_detail.html"
    context_object_name = "build"

    def get_queryset(self):
        return super().get_queryset().prefetch_related('firmwarebuildboard_set')

    def get_form_kwargs(self):
        return {
            **super().get_form_kwargs(),
            'builds': [self.get_object()],
        }


class OTAListView(MeshControlMixin, ListView):
    model = OTAUpdate
    template_name = "mesh/ota_list.html"
    ordering = "-created"
    context_object_name = "updates"
    all = False

    def get_queryset(self):
        qs = super().get_queryset().prefetch_related('recipients')
        if self.all:
            qs = qs.filter(recipients__status=OTARecipientStatus.RUNNING)
        return qs

    def get_context_data(self, **kwargs):
        return {
            **super().get_context_data(),
            "all": self.all,
        }

    def get_paginate_by(self, queryset):
        return 20 if self.all else None


class OTADetailView(MeshControlMixin, DetailView):
    model = OTAUpdate
    template_name = "mesh/ota_detail.html"
    context_object_name = "update"

    def get_queryset(self):
        return super().get_queryset().prefetch_related('recipients', 'recipients__node')
