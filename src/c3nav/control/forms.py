from django.forms import ModelForm

from c3nav.control.models import UserPermissions


class UserPermissionsForm(ModelForm):
    class Meta:
        model = UserPermissions
        exclude = ('user', )
