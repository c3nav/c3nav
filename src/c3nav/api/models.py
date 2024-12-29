import string

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.crypto import constant_time_compare, get_random_string
from django.utils.translation import gettext_lazy as _


class SecretQuerySet(models.QuerySet):
    def get_by_secret(self, secret):
        return self.filter(api_secret=secret).valid_only()

    def valid_only(self):
        return self.filter(
            Q(valid_until__isnull=True) | Q(valid_until__gte=timezone.now()),
        )


class Secret(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="api_secrets")
    name = models.CharField(_('name'), max_length=32)
    created = models.DateTimeField(auto_now_add=True, verbose_name=_('creation date'))
    api_secret = models.CharField(max_length=64, verbose_name=_('API secret'), unique=True)
    readonly = models.BooleanField(_('readonly'))
    scope_grant_permissions = models.BooleanField(_('grant map access permissions'), default=False)
    scope_editor = models.BooleanField(_('editor access'), default=False)
    scope_mesh = models.BooleanField(_('mesh access'), default=False)
    scope_load = models.BooleanField(_('load write access'), default=False)
    valid_until = models.DateTimeField(null=True, verbose_name=_('valid_until'))

    objects = models.Manager.from_queryset(SecretQuerySet)()

    def scopes_display(self):
        return [
            field.verbose_name for field in self._meta.get_fields()
            if field.name.startswith('scope_') and getattr(self, field.name)
        ] + ([_('(readonly)')] if self.readonly else [])

    class Meta:
        verbose_name = _('API secret')
        verbose_name_plural = _('API secrets')
        unique_together = [
            ('user', 'name'),
        ]


class LoginToken(models.Model):
    """
    Token for log in via API
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    secret = models.CharField(max_length=64, verbose_name=_('secret'))
    session_auth_hash = models.CharField(_('session auth hash'), max_length=128)

    class Meta:
        verbose_name = _('login tokens')
        verbose_name_plural = _('login tokens')
        default_related_name = 'login_tokens'

    def save(self, *args, **kwargs):
        if not self.secret:
            self.secret = get_random_string(64, string.ascii_letters + string.digits)
        if not self.session_auth_hash:
            # noinspection PyUnresolvedReferences
            self.session_auth_hash = self.user.get_session_auth_hash()
        super().save(*args, **kwargs)

    def get_token(self):
        return '%d:%s' % (self.pk, self.secret)

    def verify(self):
        # noinspection PyUnresolvedReferences
        return constant_time_compare(
            self.session_auth_hash,
            self.user.get_session_auth_hash()
        )

    @classmethod
    def get_by_token(cls, token: str):
        try:
            pk, secret = token.split(':', 1)
        except ValueError:
            raise cls.DoesNotExist

        if not pk.isdigit() or not secret:
            raise cls.DoesNotExist

        obj = cls.objects.select_related('user').get(pk=pk, secret=secret)

        if not obj.verify():
            obj.delete()
            raise cls.DoesNotExist

        return obj
