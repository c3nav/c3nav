from django import forms
from django.utils.translation import gettext_lazy

from c3nav.mapdata.utils.locations import get_location_for_request, LocationRedirect


class RouteForm(forms.Form):
    origin = forms.CharField()
    destination = forms.CharField()

    def __init__(self, *args, request=None, **kwargs):
        self.request = request
        super().__init__(*args, **kwargs)

    def clean_origin(self):
        location = get_location_for_request(self.cleaned_data['origin'], self.request)
        if isinstance(location, LocationRedirect):
            location = location.target
        if location is None:
            raise forms.ValidationError(gettext_lazy('Unknown origin.'))
        return location

    def clean_destination(self):
        location = get_location_for_request(self.cleaned_data['destination'], self.request)
        if isinstance(location, LocationRedirect):
            location = location.target
        if location is None:
            raise forms.ValidationError(gettext_lazy('Unknown destination.'))
        return location
