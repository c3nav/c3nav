from django.utils.functional import lazy
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import ungettext_lazy

from c3nav.mapdata.models.access import AccessPermission


def get_user_data(request):
    permissions = AccessPermission.get_for_request(request)
    result = {
        'logged_in': bool(request.user.is_authenticated),
    }
    if permissions:
        result.update({
            'title': _('not logged in'),
            'subtitle': ungettext_lazy('%d area unlocked', '%d areas unlocked', len(permissions)) % len(permissions),
            'permissions': tuple(permissions),
        })
    else:
        result.update({
            'title': _('Login'),
            'subtitle': None,
            'permissions': (),
        })
    if request.user.is_authenticated:
        result['title'] = request.user.username
    return result


get_user_data_lazy = lazy(get_user_data, dict)
