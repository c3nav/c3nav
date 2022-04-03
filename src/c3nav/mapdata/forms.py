from collections import OrderedDict

from django.conf import settings
from django.core.exceptions import ValidationError
from django.forms import CharField, ModelForm
from django.utils import timezone
from django.utils.text import capfirst, format_lazy
from django.utils.translation import get_language_info
from django.utils.translation import gettext_lazy as _

from c3nav.mapdata.fields import I18nField
from c3nav.mapdata.models.locations import Position
from c3nav.mapdata.utils.locations import get_location_by_id_for_request


class I18nModelFormMixin(ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        new_fields = OrderedDict()
        self.i18n_fields = []
        for name, form_field in self.fields.items():
            model_field = self.instance._meta.get_field(name)

            if not isinstance(model_field, I18nField):
                new_fields[name] = form_field
                continue

            values = OrderedDict((lang_code, '') for lang_code, language in settings.LANGUAGES)
            if self.instance is not None and self.instance.pk:
                values.update(getattr(self.instance, model_field.attname))

            has_values = False
            for language in values.keys():
                sub_field_name = '%s__%s' % (name, language)
                new_value = self.data.get(sub_field_name)
                if new_value is not None:
                    has_values = True
                    values[language] = new_value
                language_info = get_language_info(language)
                field_title = format_lazy(_('{field_name} ({lang})'),
                                          field_name=capfirst(model_field.verbose_name),
                                          lang=language_info['name_translated'])
                new_fields[sub_field_name] = CharField(label=field_title,
                                                       required=False,
                                                       initial=values[language].strip(),
                                                       max_length=model_field.i18n_max_length,
                                                       help_text=form_field.help_text)

            if has_values:
                self.i18n_fields.append((model_field, values))

        self.fields = new_fields

    def clean(self):
        for field, values in self.i18n_fields:
            if not field.blank and not any(values.values()):
                raise ValidationError(_('You have to choose a value for {field} in at least one language.').format(
                    field=field.verbose_name
                ))

        super().clean()

    def full_clean(self):
        super().full_clean()
        for field, values in self.i18n_fields:
            setattr(self.instance, field.attname, {lang: value for lang, value in values.items() if value})


class PositionAPIUpdateForm(ModelForm):
    secret = CharField()

    def __init__(self, *args, request=None, **kwargs):
        self.request = request
        super().__init__(*args, **kwargs)

    class Meta:
        model = Position
        fields = ['coordinates_id', 'timeout']

    def save(self, commit=True):
        self.instance.last_coordinates_update = timezone.now()
        super().save(commit)

    def clean_secret(self):
        # not called api_secret so we don't overwrite it
        api_secret = self.cleaned_data['secret']
        if api_secret != self.instance.api_secret:
            raise ValidationError(_('Wrong API secret.'))
        return api_secret

    def clean_coordinates_id(self):
        coordinates_id = self.cleaned_data['coordinates_id']
        if coordinates_id is None:
            return coordinates_id

        if not coordinates_id.startswith('c:'):
            raise ValidationError(_('Invalid coordinates.'))

        coordinates = get_location_by_id_for_request(self.cleaned_data['coordinates_id'], self.request)
        if coordinates is None:
            raise ValidationError(_('Invalid coordinates.'))

        return coordinates_id
