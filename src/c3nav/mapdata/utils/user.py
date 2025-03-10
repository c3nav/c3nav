from django.conf import settings
from django.utils.functional import lazy
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy

from c3nav.mapdata.models import DataOverlay
from c3nav.mapdata.models.access import AccessPermission, AccessRestriction
from c3nav.mapdata.models.locations import Position
from c3nav.mapdata.permissions import MapPermissionsFromRequest
from c3nav.mapdata.schemas.models import DataOverlaySchema


def get_user_data(request):
    """
    Don't use this unless needed. Use request.user_data to get this cached.
    """
    permissions = MapPermissionsFromRequest(request).access_restrictions - AccessRestriction.get_all_public()
    result = {
        'logged_in': bool(request.user.is_authenticated),
        'allow_editor': can_access_editor(request),
        'allow_control_panel': request.user_permissions.control_panel,
        'mesh_control': request.user_permissions.mesh_control,
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

    # todo: cache this
    from c3nav.mapdata.quests.base import quest_types
    result.update({
        'overlays': [DataOverlaySchema.model_validate(overlay).model_dump() for overlay in DataOverlay.objects.all()],
        'quests': (
            {key: {"label": quest.quest_type_label, "icon": quest.quest_type_icon}
             for key, quest in quest_types.items()
             if request.user.is_superuser or key in request.user_permissions.quests}
        ),
    })
    request.user_data = result
    return result


class CachedGetUserData:
    def __init__(self, request):
        self.request = request
        self.cached = None

    def __call__(self) -> dict:
        if self.cached is None:
            self.cached = get_user_data(self.request)
        return self.cached


def get_user_data_lazy(request):
    return lazy(CachedGetUserData(request), dict)()


def can_access_editor(request):
    return settings.PUBLIC_EDITOR or request.user_permissions.editor_access
