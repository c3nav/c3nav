from django.forms import ModelForm, MultipleChoiceField
from django.utils.translation import ugettext_lazy as _

from c3nav.access.models import AccessToken, AccessUser
from c3nav.mapdata.models import AreaLocation


def get_permissions_field(request):
    locations = AreaLocation.objects.filter(routing_inclusion='needs_permission')

    has_operator = True
    try:
        request.user.operator
    except:
        has_operator = False

    OPTIONS = []
    can_full = False
    if request.user.is_superuser:
        can_full = True
    elif has_operator:
        can_award = request.user.operator.can_award_permissions.split(';')
        can_full = ':full' in can_award
        if not can_full:
            locations = locations.filter(name__in=can_award)
    else:
        locations = []

    if can_full:
        OPTIONS.append((':full', _('Full Permissions')))

    OPTIONS += [(location.name, location.title) for location in locations]
    return MultipleChoiceField(choices=OPTIONS, required=True)


class AccessTokenForm(ModelForm):
    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['permissions'] = get_permissions_field(request)

    class Meta:
        model = AccessToken
        fields = ['permissions', 'description', 'expires']

    def clean_permissions(self):
        data = self.cleaned_data['permissions']
        if ':full' in data:
            data = [':full']
        data = ';'.join(data)
        return data


class AccessUserForm(ModelForm):
    class Meta:
        model = AccessUser
        fields = ['user_url', 'description']
