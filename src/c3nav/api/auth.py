from django.utils.translation import gettext_lazy as _
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed


class APISecretAuthentication(TokenAuthentication):
    def authenticate_credentials(self, key):
        from c3nav.control.models import UserPermissions

        try:
            user_perms = UserPermissions.objects.exclude(api_secret='').exclude(api_secret__isnull=True).filter(
                api_secret=key
            ).get()
        except UserPermissions.DoesNotExist:
            raise AuthenticationFailed(_('Invalid token.'))

        if not user_perms.user.is_active:
            raise AuthenticationFailed(_('User inactive or deleted.'))

        return (user_perms.user, user_perms)
