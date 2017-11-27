from django import forms
from django.utils.translation import ugettext_lazy

from c3nav.mapdata.utils.locations import locations_for_request


class RouteForm(forms.Form):
    origin = forms.IntegerField(min_value=1)
    destination = forms.IntegerField(min_value=1)

    def __init__(self, *args, request=None, **kwargs):
        self.request = request
        super().__init__(*args, **kwargs)

    def clean_origin(self):
        try:
            return locations_for_request(self.request)[self.cleaned_data['origin']]
        except KeyError:
            raise forms.ValidationError(ugettext_lazy('Unknown origin.'))

    def clean_destination(self):
        try:
            return locations_for_request(self.request)[self.cleaned_data['destination']]
        except KeyError:
            raise forms.ValidationError(ugettext_lazy('Unknown destination.'))
