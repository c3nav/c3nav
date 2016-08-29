from django.db import models
from django.utils.translation import ugettext_lazy as _


class Level(models.Model):
    """
    A map level (-1, 0, 1, 2…)
    """
    name = models.CharField(_('level name'), max_length=50, unique=True,
                            help_text=_('Usually just an integer (e.g. -1, 0, 1, 2)'))
    altitude = models.DecimalField(_('level altitude'), null=True, max_digits=6, decimal_places=2)
    package = models.ForeignKey('Package', on_delete=models.CASCADE, related_name='levels',
                                verbose_name=_('map package'))

    class Meta:
        ordering = ['altitude']
