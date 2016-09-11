from collections import OrderedDict

from django.db import models
from django.utils.translation import ugettext_lazy as _


class Package(models.Model):
    """
    A c3nav map package
    """
    name = models.SlugField(_('package identifier'), primary_key=True, max_length=50,
                            help_text=_('e.g. de.c3nav.33c3.base'))
    depends = models.ManyToManyField('Package')

    bottom = models.DecimalField(_('bottom coordinate'), null=True, max_digits=6, decimal_places=2)
    left = models.DecimalField(_('left coordinate'), null=True, max_digits=6, decimal_places=2)
    top = models.DecimalField(_('top coordinate'), null=True, max_digits=6, decimal_places=2)
    right = models.DecimalField(_('right coordinate'), null=True, max_digits=6, decimal_places=2)

    directory = models.CharField(_('folder name'), max_length=100)

    @classmethod
    def fromfile(cls, data, directory):
        kwargs = {
            'directory': directory
        }

        if 'name' not in data:
            raise ValueError('pkg.json: missing package name.')
        kwargs['name'] = data['name']

        depends = data.get('depends', [])
        if not isinstance(depends, list):
            raise TypeError('pkg.json: depends has to be a list')
        kwargs['depends'] = depends

        if 'bounds' in data:
            bounds = data['bounds']
            if len(bounds) != 2 or len(bounds[0]) != 2 or len(bounds[1]) != 2:
                raise ValueError('pkg.json: Invalid bounds format.')
            if not all(isinstance(i, (float, int)) for i in sum(bounds, [])):
                raise ValueError('pkg.json: All bounds coordinates have to be int or float.')
            if bounds[0][0] >= bounds[1][0] or bounds[0][1] >= bounds[1][1]:
                raise ValueError('pkg.json: bounds: lower coordinate has to be first.')
            (kwargs['bottom'], kwargs['left']), (kwargs['top'], kwargs['right']) = bounds

        return kwargs

    @property
    def package(self):
        return self

    def tofile(self):
        data = OrderedDict()
        data['name'] = self.name
        if self.bottom is not None:
            data['bounds'] = ((float(self.bottom), float(self.left)), (float(self.top), float(self.right)))
        if self.depends.exists():
            data['depends'] = tuple(package.name for package in self.depends.all().order_by('name'))

        return data

    def __str__(self):
        return self.name
