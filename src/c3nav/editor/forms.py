from django.forms import ModelForm
from django.forms.widgets import HiddenInput

from ..mapdata.models import Feature


class FeatureForm(ModelForm):
    def __init__(self, *args, feature_type, **kwargs):
        self.feature_type = feature_type
        super().__init__(*args, **kwargs)
        self.fields['level'].widget = HiddenInput()
        self.fields['geometry'].widget = HiddenInput()

    class Meta:
        model = Feature
        fields = ['name', 'package', 'level', 'geometry']
