from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin


class MeshControlMixin(UserPassesTestMixin, LoginRequiredMixin):
    login_url = 'site.login'
    user_permission = None

    def test_func(self):
        if not self.request.user_permissions.mesh_control:
            return False
        if not self.user_permission:
            return True
        return getattr(self.request.user_permissions, self.user_permission)
