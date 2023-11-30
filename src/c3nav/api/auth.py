from django.utils.translation import gettext_lazy as _
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed


class APISecretAuthentication(TokenAuthentication):
    def authenticate_credentials(self, key):
        try:
            from c3nav.api.models import Secret
            secret = Secret.objects.filter(api_secret=key).select_related('user', 'user__permissions')
            # todo: auth scopes are ignored here, we need to get rid of this
        except Secret.DoesNotExist:
            raise AuthenticationFailed(_('Invalid token.'))

        if not secret.user.is_active:
            raise AuthenticationFailed(_('User inactive or deleted.'))

        return (secret.user, secret)
