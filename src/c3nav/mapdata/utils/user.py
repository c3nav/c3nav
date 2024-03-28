from django.conf import settings
from django.utils.functional import lazy
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy

from c3nav.mapdata.models.access import AccessPermission, AccessRestriction
from c3nav.mapdata.models.locations import Position


def get_user_data(request):
    permissions = AccessPermission.get_for_request(request) - AccessRestriction.get_all_public()
    result = {
        'logged_in': bool(request.user.is_authenticated),
        'allow_editor': can_access_editor(request),
        'allow_control_panel': request.user_permissions.control_panel,
        'has_positions': Position.user_has_positions(request.user)
    }
    if permissions:
        result.update({
            'title': _('Login'),
            'subtitle': ngettext_lazy('%d area unlocked', '%d areas unlocked', len(permissions)) % len(permissions),
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


def can_access_editor(request):
    return settings.PUBLIC_EDITOR or request.user_permissions.editor_access
