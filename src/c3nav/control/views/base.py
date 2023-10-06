from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.views.generic import TemplateView


class ControlPanelMixin(UserPassesTestMixin, LoginRequiredMixin):
    login_url = 'site.login'
    user_permission = None

    def test_func(self):
        if not self.request.user_permissions.control_panel:
            return False
        if not self.user_permission:
            return True
        return getattr(self.request.user_permissions, self.user_permission)


def control_panel_view(func):
    @wraps(func)
    def wrapped_func(request, *args, **kwargs):
        if not request.user_permissions.control_panel:
            raise PermissionDenied
        return func(request, *args, **kwargs)
    return login_required(login_url='site.login')(wrapped_func)


class ControlPanelIndexView(ControlPanelMixin, TemplateView):
    template_name = "control/index.html"
