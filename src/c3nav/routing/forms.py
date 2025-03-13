from django import forms
from django.utils.translation import gettext_lazy

from c3nav.mapdata.locations import LocationRedirect, LocationManager


class RouteForm(forms.Form):
    origin = forms.CharField()
    destination = forms.CharField()

    def clean_origin(self):
        location = LocationManager.get(self.cleaned_data['origin'])
        if isinstance(location, LocationRedirect):
            location = location.target
        if location is None:
            raise forms.ValidationError(gettext_lazy('Unknown origin.'))
        return location

    def clean_destination(self):
        location = LocationManager.get(self.cleaned_data['destination'])
        if isinstance(location, LocationRedirect):
            location = location.target
        if location is None:
            raise forms.ValidationError(gettext_lazy('Unknown destination.'))
        return location
