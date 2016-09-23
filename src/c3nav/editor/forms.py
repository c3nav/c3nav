from collections import OrderedDict

from django.conf import settings
from django.forms import CharField, ModelForm, ValidationError
from django.forms.widgets import HiddenInput
from django.utils.translation import ugettext_lazy as _

from ..mapdata.models import Feature


class FeatureForm(ModelForm):
    def __init__(self, *args, feature_type, **kwargs):
        self.feature_type = feature_type
        super().__init__(*args, **kwargs)
        self.fields['level'].widget = HiddenInput()
        self.fields['geometry'].widget = HiddenInput()

        titles = OrderedDict((lang_code, '') for lang_code, language in settings.LANGUAGES)
        if self.instance is not None and self.instance.pk:
            titles.update(self.instance.titles)

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
