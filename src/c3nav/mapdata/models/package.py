from django.conf import settings
from django.db import models
from django.utils.translation import ugettext_lazy as _

from c3nav.mapdata.lastupdate import set_last_mapdata_update


class Package(models.Model):
    """
    A c3nav map package
    """
    name = models.SlugField(_('package identifier'), unique=True, max_length=50,
                            help_text=_('e.g. de.c3nav.33c3.base'))
    depends = models.ManyToManyField('Package')
    home_repo = models.URLField(_('URL to the home git repository'), null=True)
    commit_id = models.CharField(_('current commit id'), max_length=40, null=True)

    bottom = models.DecimalField(_('bottom coordinate'), null=True, max_digits=6, decimal_places=2)
    left = models.DecimalField(_('left coordinate'), null=True, max_digits=6, decimal_places=2)
    top = models.DecimalField(_('top coordinate'), null=True, max_digits=6, decimal_places=2)
    right = models.DecimalField(_('right coordinate'), null=True, max_digits=6, decimal_places=2)

    directory = models.CharField(_('folder name'), max_length=100)

    class Meta:
        verbose_name = _('Map Package')
        verbose_name_plural = _('Map Packages')
        default_related_name = 'packages'

    @property
    def package(self):
        return self

    @property
    def bounds(self):
        if self.bottom is None:
            return None
        return (float(self.bottom), float(self.left)), (float(self.top), float(self.right))

    @property
    def public(self):
        return self.name in settings.PUBLIC_PACKAGES

    def save(self, *args, **kwargs):
        with set_last_mapdata_update():
            super().save(*args, **kwargs)

    def __str__(self):
        return self.name
