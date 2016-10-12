from collections import OrderedDict

from django.conf import settings
from django.db import models
from django.utils.translation import ugettext_lazy as _


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

    @classmethod
    def get_path_regex(cls):
        return '^package.json$'

    def get_filename(self):
        return 'package.json'

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

    @classmethod
    def fromfile(cls, data, file_path):
        kwargs = {}

        if 'name' not in data:
            raise ValueError('missing package name.')
        kwargs['name'] = data['name']

        depends = data.get('depends', [])
        if not isinstance(depends, list):
            raise TypeError('depends has to be a list')
        kwargs['depends'] = depends

        kwargs['home_repo'] = data['home_repo'] if 'home_repo' in data else None

        if 'bounds' in data:
            bounds = data['bounds']
            if len(bounds) != 2 or len(bounds[0]) != 2 or len(bounds[1]) != 2:
                raise ValueError('Invalid bounds format.')
            if not all(isinstance(i, (float, int)) for i in sum(bounds, [])):
                raise ValueError('All bounds coordinates have to be int or float.')
            if bounds[0][0] >= bounds[1][0] or bounds[0][1] >= bounds[1][1]:
                raise ValueError('bounds: lower coordinate has to be first.')
        else:
            bounds = (None, None), (None, None)
        (kwargs['bottom'], kwargs['left']), (kwargs['top'], kwargs['right']) = bounds

        return kwargs

    # noinspection PyMethodMayBeStatic
    def tofilename(self):
        return 'package.json'

    def tofile(self):
        data = OrderedDict()
        data['name'] = self.name
        if self.home_repo is not None:
            data['home_repo'] = self.home_repo
        if self.depends.exists():
            data['depends'] = tuple(self.depends.all().order_by('name').values_list('name', flat=True))
        if self.bottom is not None:
            data['bounds'] = ((float(self.bottom), float(self.left)), (float(self.top), float(self.right)))

        return data

    def __str__(self):
        return self.name
