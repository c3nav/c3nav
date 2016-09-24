from django.db import models
from django.utils.translation import ugettext_lazy as _


class Level(models.Model):
    """
    A map level (-1, 0, 1, 2…)
    """
    name = models.SlugField(_('level name'), primary_key=True, max_length=50,
                            help_text=_('Usually just an integer (e.g. -1, 0, 1, 2)'))
    altitude = models.DecimalField(_('level altitude'), null=True, max_digits=6, decimal_places=2)
    package = models.ForeignKey('mapdata.Package', on_delete=models.CASCADE, related_name='levels',
                                verbose_name=_('map package'))

    path_regex = r'^levels/'

    def tofilename(self):
        return 'levels/%s.json' % self.name

    @classmethod
    def fromfile(cls, data):
        if 'altitude' not in data:
            raise ValueError('missing altitude.')

        if not isinstance(data['altitude'], (int, float)):
            raise ValueError('altitude has to be int or float.')

        return {
            'altitude': data['altitude'],
        }

    def tofile(self):
        return {
            'altitude': float(self.altitude)
        }
