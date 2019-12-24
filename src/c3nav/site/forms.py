from django.forms import ModelForm

from c3nav.mapdata.forms import I18nModelFormMixin
from c3nav.mapdata.models.report import Report


class ReportIssueForm(I18nModelFormMixin, ModelForm):
    class Meta:
        model = Report
        fields = ['title', 'description']


class ReportMissingLocationForm(I18nModelFormMixin, ModelForm):
    class Meta:
        model = Report
        fields = ['title', 'description', 'created_title', 'created_groups']
