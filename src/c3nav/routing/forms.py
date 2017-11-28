from django import forms
from django.utils.translation import ugettext_lazy

from c3nav.mapdata.utils.locations import get_location_by_id_for_request


class RouteForm(forms.Form):
    origin = forms.CharField()
    destination = forms.CharField()

    def __init__(self, *args, request=None, **kwargs):
        self.request = request
        super().__init__(*args, **kwargs)

    def clean_origin(self):
        location = get_location_by_id_for_request(self.cleaned_data['origin'], self.request)
        if location is None:
            raise forms.ValidationError(ugettext_lazy('Unknown origin.'))
        return location

    def clean_destination(self):
        location = get_location_by_id_for_request(self.cleaned_data['destination'], self.request)
        if location is None:
            raise forms.ValidationError(ugettext_lazy('Unknown destination.'))
        return location
