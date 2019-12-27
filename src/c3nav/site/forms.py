from operator import attrgetter

from django.db import transaction
from django.forms import Form, ModelChoiceField, ModelForm
from django.utils.translation import ugettext_lazy as _

from c3nav.mapdata.forms import I18nModelFormMixin
from c3nav.mapdata.models.locations import Position
from c3nav.mapdata.models.report import Report, ReportUpdate


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

    def save(self):
        with transaction.atomic():
            super().save()
            report = self.instance.report
            if self.instance.open is not None:
                report.open = self.instance.open
            if self.instance.assigned_to:
                report.assigned_to = self.instance.assigned_to
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
