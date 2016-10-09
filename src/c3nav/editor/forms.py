from collections import OrderedDict

from django.conf import settings
from django.forms import CharField, Form, ModelForm, ValidationError
from django.forms.models import ModelChoiceField
from django.forms.widgets import HiddenInput
from django.utils.translation import ugettext_lazy as _

from c3nav.mapdata.models import Feature, Package
from c3nav.mapdata.permissions import get_unlocked_packages


class FeatureForm(ModelForm):
    def __init__(self, *args, feature_type, request=None, **kwargs):
        self.feature_type = feature_type
        self.request = request
        super().__init__(*args, **kwargs)
        self.fields['level'].widget = HiddenInput()
        self.fields['geometry'].widget = HiddenInput()

        titles = OrderedDict((lang_code, '') for lang_code, language in settings.LANGUAGES)
        if self.instance is not None and self.instance.pk:
            self.fields['name'].disabled = True
            if not settings.DIRECT_EDITING:
                self.fields['package'].widget = HiddenInput()
                self.fields['package'].disabled = True
            titles.update(self.instance.titles)
        elif not settings.DIRECT_EDITING:
            unlocked_packages = get_unlocked_packages(request)
            if len(unlocked_packages) == 1:
                self.fields['package'].widget = HiddenInput()
                self.fields['package'].initial = next(iter(unlocked_packages))
            else:
                self.fields['package'] = ModelChoiceField(
                    queryset=Package.objects.filter(name__in=unlocked_packages)
                )

        language_titles = dict(settings.LANGUAGES)
        for language in titles.keys():
            new_title = self.data.get('title_' + language)
            if new_title is not None:
                titles[language] = new_title
            self.fields['title_' + language] = CharField(label=language_titles.get(language, language), required=False,
                                                         initial=titles[language].strip(), max_length=50)
        self.titles = titles

    def clean(self):
        super().clean()
        if not any(self.titles.values()):
            raise ValidationError(
                _('You have to select a title in at least one language.')
            )

    def get_languages(self):
        pass

    class Meta:
        # generate extra fields in the number specified via extra_fields
        model = Feature
        fields = ['name', 'package', 'level', 'geometry']


class CommitForm(Form):
    commit_msg = CharField(label=_('Commit message'), max_length=100)
