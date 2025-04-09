import string
from datetime import timedelta
from operator import attrgetter

from django.core.exceptions import ValidationError
from django.db import transaction
from django.forms import BooleanField, Form, IntegerField, ModelChoiceField, ModelForm
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.translation import gettext_lazy as _

from c3nav.api.models import Secret
from c3nav.mapdata.forms import I18nModelFormMixin
from c3nav.mapdata.models.locations import Position, LocationGroup, SpecificLocation
from c3nav.mapdata.models.report import Report, ReportUpdate
from c3nav.site.compliance import ComplianceCheckboxFormMixin


class ReportIssueForm(ComplianceCheckboxFormMixin, I18nModelFormMixin, ModelForm):
    class Meta:
        model = Report
        fields = ['title', 'description']


class DeleteAccountForm(Form):
    confirm = BooleanField(label=_('Yes, i really want to delete my account.'), required=True)


class ReportMissingLocationForm(I18nModelFormMixin, ModelForm):
    def __init__(self, *args, parent=None, request=None, **kwargs):
        initial = {"created_parents": [parent] if parent else []}
        if parent and parent.can_report_missing == SpecificLocation.CanReportMissing.SINGLE_IMAGE:
            initial["title"] = _("Image for %s") % parent.title
            initial["description"] = _('(feel free to add more description if it makes sense)')

        super().__init__(*args, initial=initial, **kwargs)
        if parent:
            self.fields['created_parents'].disabled = True
            # todo: in other places we don't set the queryset explicitly and the filter gets on django init. fix that.
            self.fields['created_parents'].queryset = SpecificLocation.objects.filter(pk=parent.pk)

            if parent.can_report_missing == SpecificLocation.CanReportMissing.SINGLE_IMAGE:
                self.fields['created_title__en'].initial = parent.title
            else:
                self.fields.pop('image')
        else:
            self.fields.pop('image')
            exists = SpecificLocation.objects.filter(
                can_report_missing=SpecificLocation.CanReportMissing.MULTIPLE
            ).exists()
            if exists:
                self.fields['created_parents'].queryset = SpecificLocation.objects.filter(
                    can_report_missing=SpecificLocation.CanReportMissing.MULTIPLE
                )
            else:
                self.fields['created_parents'].queryset = SpecificLocation.objects.none()
                self.fields['created_parents'].widget = self.fields['created_parents'].hidden_widget()
        self.fields['created_parents'].label_from_instance = lambda obj: obj.title

    class Meta:
        model = Report
        fields = ['title', 'description', 'created_title', 'created_parents', 'image']


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
        fields = ['name' ,"short_name", 'timeout']


class PositionSetForm(Form):
    position = ModelChoiceField(Position.objects.none())

    def __init__(self, request, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['position'].queryset = Position.objects.filter(owner=request.user)
        self.fields['position'].label_from_instance = attrgetter('name')


class APISecretForm(ModelForm):
    valid_for_days = IntegerField(min_value=0, max_value=90, label=_('valid for (days)'), initial=7)
    valid_for_hours = IntegerField(min_value=0, max_value=24, label=_('valid for (hours)'), initial=0)

    def __init__(self, *args, request, **kwargs):
        self.request = request
        super().__init__(*args, **kwargs)
        if not self.request.user_permissions.grant_permissions:
            self.fields.pop('scope_grant_permissions', None)
        if not self.request.user_permissions.editor_access:
            self.fields.pop('scope_editor', None)
        if not self.request.user_permissions.mesh_control:
            self.fields.pop('scope_mesh', None)

    class Meta:
        model = Secret
        fields = ['name', 'readonly', 'scope_grant_permissions', 'scope_editor', 'scope_mesh', "scope_load"]

    def clean(self):
        try:
            self.instance.user = self.request.user
            self.instance.name = self.cleaned_data['name']
            self.instance.validate_unique()
        except ValidationError as e:
            self._update_errors(e)
        return super().clean()

    def save(self, *args, **kwargs):
        self.instance.valid_until = (
                timezone.now()
                + timedelta(days=self.cleaned_data['valid_for_days'])
                + timedelta(hours=self.cleaned_data['valid_for_hours'])
        )
        self.instance.user = self.request.user
        self.instance.api_secret = (
            '%d-%s' % (self.request.user.pk, get_random_string(62, string.ascii_letters + string.digits))
        )[:64]

        return super().save(*args, **kwargs)
