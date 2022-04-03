import string

from django.conf import settings
from django.db import models
from django.utils.crypto import constant_time_compare, get_random_string
from django.utils.translation import gettext_lazy as _


class Token(models.Model):
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
