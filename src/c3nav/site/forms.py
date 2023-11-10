from dataclasses import dataclass
from dataclasses import replace as dataclass_replace
from functools import cached_property
from operator import attrgetter
from typing import Any, Sequence

from django.db import transaction
from django.forms import BooleanField, ChoiceField, Form, ModelChoiceField, ModelForm
from django.utils.translation import gettext_lazy as _

from c3nav.mapdata.forms import I18nModelFormMixin
from c3nav.mapdata.models.locations import Position
from c3nav.mapdata.models.report import Report, ReportUpdate
from c3nav.mesh.messages import MeshMessageType
from c3nav.mesh.models import FirmwareBuild, HardwareDescription, MeshNode, OTAUpdate


class ReportIssueForm(I18nModelFormMixin, ModelForm):
    class Meta:
        model = Report
        fields = ['title', 'description']


class ReportMissingLocationForm(I18nModelFormMixin, ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['created_groups'].label_from_instance = lambda obj: obj.title

    class Meta:
        model = Report
        fields = ['title', 'description', 'created_title', 'created_groups']


class ReportUpdateForm(ModelForm):
    def __init__(self, request, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        self.fields['open'].label = _('change status')
        self.fields['open'].widget.choices = (
            ('unknown', _('don\'t change')),
            ('true', _('open')),
            ('false', _('closed')),
        )

    def save(self, commit=True):
        with transaction.atomic():
            super().save(commit=commit)
            report = self.instance.report
            if self.instance.open is not None:
                report.open = self.instance.open
            if self.instance.assigned_to:
                report.assigned_to = self.instance.assigned_to
            if commit:
                report.save()

    class Meta:
        model = ReportUpdate
        fields = ['open', 'comment', 'public']


class PositionForm(ModelForm):
    class Meta:
        model = Position
        fields = ['name', 'timeout']


class PositionSetForm(Form):
    position = ModelChoiceField(Position.objects.none())

    def __init__(self, request, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['position'].queryset = Position.objects.filter(owner=request.user)
        self.fields['position'].label_from_instance = attrgetter('name')


@dataclass
class OTAFormGroup:
    hardware: HardwareDescription
    builds: Sequence[FirmwareBuild]
    fields: dict[str, tuple[MeshNode, Any]]

    @cached_property
    def builds_by_id(self) -> dict[int, FirmwareBuild]:
        return {build.pk: build for build in self.builds}


class OTACreateForm(Form):
    def __init__(self, builds: Sequence[FirmwareBuild], *args, **kwargs):
        super().__init__(*args, **kwargs)

        nodes: Sequence[MeshNode] = MeshNode.objects.prefetch_last_messages(
            MeshMessageType.CONFIG_BOARD
        ).prefetch_firmwares().prefetch_ota()

        builds_by_hardware = {}
        for build in builds:
            for hardware_desc in build.get_hardware_descriptions():
                builds_by_hardware.setdefault(hardware_desc, []).append(build)

        nodes_by_hardware = {}
        for node in nodes:
            nodes_by_hardware.setdefault(node.get_hardware_description(), []).append(node)

        self._groups: list[OTAFormGroup] = []
        for hardware, hw_nodes in sorted(nodes_by_hardware.items(), key=lambda k: len(k[1]), reverse=True):
            try:
                hw_builds = builds_by_hardware[hardware]
            except KeyError:
                continue
            choices = [
                ('', '---'),
                *((build.pk, build.variant) for build in hw_builds)
            ]

            group = OTAFormGroup(
                hardware=hardware,
                builds=hw_builds,
                fields={
                    f'build_{node.pk}': (node, (
                        ChoiceField(choices=choices, required=False)
                        if len(hw_builds) > 1
                        else BooleanField(required=False)
                    )) for node in hw_nodes
                }
            )
            for name, (node, hw_field) in group.fields.items():
                self.fields[name] = hw_field
            self._groups.append(group)

    @property
    def groups(self) -> list[OTAFormGroup]:
        return [
            dataclass_replace(group, fields={
                name: (node, self[name])
                for name, (node, hw_field) in group.fields.items()
            })
            for group in self._groups
        ]

    @property
    def selected_builds(self):
        build_nodes = {}
        for group in self._groups:
            for name, (node, hw_field) in group.fields.items():
                value = self.cleaned_data.get(name, None)
                if not value:
                    continue
                if len(group.builds) == 1:
                    build_nodes.setdefault(group.builds[0], []).append(node)
                else:
                    build_nodes.setdefault(group.builds[0], []).append(group.builds_by_id[int(value)])
        return build_nodes

    def save(self) -> list[OTAUpdate]:
        updates = []
        with transaction.atomic():
            for build, nodes in self.selected_builds.items():
                update = OTAUpdate.objects.create(build=build)
                for node in nodes:
                    update.recipients.create(node=node)
                updates.append(update)
        return updates
