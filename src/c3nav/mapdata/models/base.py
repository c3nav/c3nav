from collections import OrderedDict

from django.db import models
from django.utils.translation import ugettext_lazy as _


class MapdataModel(models.Model):
    name = models.SlugField(_('Name'), max_length=50)
    package = models.ForeignKey('mapdata.Package', on_delete=models.CASCADE, verbose_name=_('map package'))

    @classmethod
    def get_path_prefix(cls):
        return cls._meta.default_related_name + '/'

    @classmethod
    def get_path_regex(cls):
        return r'^' + cls.get_path_prefix()

    def get_filename(self):
        return self._meta.default_related_name + '/' + self.name + '.json'

    @classmethod
    def fromfile(cls, data, file_path):
        kwargs = {}
        return kwargs

    def tofile(self):
        return OrderedDict()

    class Meta:
        abstract = True
        unique_together = ('package', 'name')

