from django.db import models
from django.utils.translation import ugettext_lazy as _


class Source(models.Model):
    """
    A map source, images of levels that can be useful as backgrounds for the map editor
    """
    name = models.SlugField(_('source name'), primary_key=True, max_length=50)
    package = models.ForeignKey('mapdata.Package', on_delete=models.CASCADE, related_name='sources',
                                verbose_name=_('map package'))

    bottom = models.DecimalField(_('bottom coordinate'), max_digits=6, decimal_places=2)
    left = models.DecimalField(_('left coordinate'), max_digits=6, decimal_places=2)
    top = models.DecimalField(_('top coordinate'), max_digits=6, decimal_places=2)
    right = models.DecimalField(_('right coordinate'), max_digits=6, decimal_places=2)

    path_regex = r'^sources/'

    @classmethod
    def max_bounds(cls):
        result = cls.objects.all().aggregate(models.Min('bottom'), models.Min('left'),
                                             models.Max('top'), models.Max('right'))
        return ((float(result['bottom__min']), float(result['left__min'])),
                (float(result['top__max']), float(result['right__max'])))

    @property
    def bounds(self):
        return (float(self.bottom), float(self.left)), (float(self.top), float(self.right))

    def tofilename(self):
        return 'sources/%s.json' % self.name

    @classmethod
    def fromfile(cls, data):
        kwargs = {}

        if 'bounds' not in data:
            raise ValueError('missing bounds.')

        bounds = data['bounds']
        if len(bounds) != 2 or len(bounds[0]) != 2 or len(bounds[1]) != 2:
            raise ValueError('Invalid bounds format.')
        if not all(isinstance(i, (float, int)) for i in sum(bounds, [])):
            raise ValueError('All bounds coordinates have to be int or float.')
        if bounds[0][0] >= bounds[1][0] or bounds[0][1] >= bounds[1][1]:
            raise ValueError('bounds: lower coordinate has to be first.')
        (kwargs['bottom'], kwargs['left']), (kwargs['top'], kwargs['right']) = bounds

        return kwargs

    def tofile(self):
        return {
            'bounds': ((float(self.bottom), float(self.left)), (float(self.top), float(self.right)))
        }
