from django.db import models
from django.utils.translation import gettext_lazy as _


class GroundAltitude(models.Model):
    """
    A pre-defined ground altitude
    """
    name = models.CharField(_('Name'), unique=True, max_length=70)  # a slugfield would forbid periods
    altitude = models.DecimalField(_('altitude'), null=False, max_digits=6, decimal_places=2)

    class Meta:
        verbose_name = _('Ground Altitude')
        verbose_name_plural = _('Ground altitudes')
        default_related_name = "groundaltitudes"

    @property
    def title(self):
        return f'{self.name} ({self.altitude}m)'
