import string
from datetime import timedelta

from django.contrib.auth.models import User
from django.db import models, transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.translation import ugettext_lazy as _


class AccessOperator(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='operator')
    description = models.TextField(_('description'), null=True, blank=True)
    can_award_permissions = models.CharField(_('can award permissions'), max_length=2048)
    access_from = models.DateTimeField(_('has access from'), null=True, blank=True)
    access_until = models.DateTimeField(_('has access until'), null=True, blank=True)

    class Meta:
        verbose_name = _('Access Operator')
        verbose_name_plural = _('Access Operator')

    def __str__(self):
        return str(self.user)


class AccessUser(models.Model):
    user_url = models.CharField(_('access name'), unique=True, max_length=200,
                                help_text=_('Usually an URL to a profile somewhere'))
    author = models.ForeignKey(AccessOperator, on_delete=models.PROTECT, null=True, blank=True,
                               verbose_name=_('creator'))
    description = models.TextField(_('description'), max_length=200, null=True, blank=True)
    creation_date = models.DateTimeField(_('creation date'), auto_now_add=True)

    class Meta:
        verbose_name = _('Access User')
        verbose_name_plural = _('Access Users')

    @property
    def valid_tokens(self):
        return self.tokens.filter(Q(expired=False) | Q(expires__isnull=False, expires__lt=timezone.now()))

    def new_token(self, **kwargs):
        kwargs['secret'] = get_random_string(42, string.ascii_letters + string.digits)
        return self.tokens.create(**kwargs)

    def __str__(self):
        return self.user_url


class AccessToken(models.Model):
    user = models.ForeignKey(AccessUser, on_delete=models.CASCADE, related_name='tokens',
                             verbose_name=_('Access User'))
    author = models.ForeignKey(User, on_delete=models.PROTECT, verbose_name=_('creator'), null=True, blank=True)
    permissions = models.CharField(_('permissions'), max_length=2048)
    description = models.CharField(_('description'), max_length=200)
    creation_date = models.DateTimeField(_('creation date'), auto_now_add=True)
    expires = models.DateTimeField(null=True, blank=True)
    expired = models.BooleanField(_('is expired'), default=False)
    activated = models.BooleanField(_('activated'), default=False)
    secret = models.CharField(_('activation secret'), max_length=42)

    class Meta:
        verbose_name = _('Access Token')
        verbose_name_plural = _('Access Tokens')

    @property
    def activation_url(self):
        if self.activated:
            return None
        return reverse('access.activate', kwargs={'pk': self.pk, 'secret': self.secret})

    def new_instance(self):
        with transaction.atomic():
            for instance in self.instances.filter(expires__isnull=True):
                instance.expires = timezone.now()+timedelta(seconds=5)
                instance.save()

            self.instances.filter(expires__isnull=False, expires__lt=timezone.now()).delete()

            secret = get_random_string(42, string.ascii_letters+string.digits)
            self.instances.create(secret=secret)
        return '%d:%s' % (self.pk, secret)

    def __str__(self):
        return '%s #%d' % (_('Access Token'), self.id)


class AccessTokenInstance(models.Model):
    access_token = models.ForeignKey(AccessToken, on_delete=models.CASCADE, related_name='instances',
                                     verbose_name=_('Access Token'))
    secret = models.CharField(_('access secret'), max_length=42)
    creation_date = models.DateTimeField(_('creation date'), auto_now_add=True)
    expires = models.DateTimeField(null=True)

    class Meta:
        verbose_name = _('Access Token Instance')
        verbose_name_plural = _('Access Tokens Instance')
