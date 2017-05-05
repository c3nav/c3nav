from django.utils.translation import ugettext_lazy as _

from c3nav.mapdata.models.base import Feature


class Elevator(Feature):
    """
    An elevator.
    """
    class Meta:
        verbose_name = _('Elevator')
        verbose_name_plural = _('Elevators')
        default_related_name = 'elevators'

    def __str__(self):
        return self.name
