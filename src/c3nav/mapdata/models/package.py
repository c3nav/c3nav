from django.db import models
from django.utils.translation import ugettext_lazy as _


class Package(models.Model):
    """
    A c3nav map package
    """
    name = models.CharField(_('package identifier'), unique=True, max_length=50,
                            help_text=_('e.g. de.c3nav.33c3.base'))

    bottom = models.DecimalField(_('bottom coordinate'), null=True, max_digits=6, decimal_places=2)
    left = models.DecimalField(_('left coordinate'), null=True, max_digits=6, decimal_places=2)
    top = models.DecimalField(_('top coordinate'), null=True, max_digits=6, decimal_places=2)
    right = models.DecimalField(_('right coordinate'), null=True, max_digits=6, decimal_places=2)
