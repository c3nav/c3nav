from django.db import models
from django.utils.translation import ugettext_lazy as _


class Level(models.Model):
    """
    A map level (-1, 0, 1, 2…)
    """
    name = models.SlugField(_('level name'), primary_key=True, max_length=50,
                            help_text=_('Usually just an integer (e.g. -1, 0, 1, 2)'))
    altitude = models.DecimalField(_('level altitude'), null=True, max_digits=6, decimal_places=2)
    package = models.ForeignKey('Package', on_delete=models.CASCADE, related_name='levels',
                                verbose_name=_('map package'))

    @classmethod
    def fromfile(cls, data, package, name):
        if 'altitude' not in data:
            raise ValueError('%s.json: missing altitude.' % name)

        if not isinstance(data['altitude'], (int, float)):
            raise ValueError('%s.json: altitude has to be in or float.')

        return {
            'name': name,
            'package': package,
            'altitude': data['altitude'],
        }

    def tofile(self):
        return {
            'altitude': float(self.altitude)
        }
