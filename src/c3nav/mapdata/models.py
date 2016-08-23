from django.contrib.gis.db import models
from django.utils.translation import ugettext_lazy as _

from parler.models import TranslatedFields

from ..models import TranslatableGeoModel


class MapPackage(TranslatableGeoModel):
    """
    A c3nav map package
    """
    name = models.CharField(_('package identifier'), max_length=50, help_text=_('e.g. de.c3nav.33c3')),
    width = models.IntegerField(_('map width'), max_length=50, null=True, help_text='in meters'),
    height = models.IntegerField(_('map height'), max_length=50, null=True, help_text='in meters'),
    extends = models.ForeignKey('self', on_delete=models.PROTECT, null=True, related_name='extended_by',
                                verbose_name=_('extends map package'))

    translations = TranslatedFields(
        title=models.CharField(_('package title'), max_length=50),
    )


class MapLevel(TranslatableGeoModel):
    """
    A map level (-1, 0, 1, 2…)
    """
    name = models.CharField(_('level name'), max_length=50, help_text=_('Usually just an integer (e.g. -1, 0, 1, 2)')),
    package = models.ForeignKey('MapPackage', on_delete=models.PROTECT, related_name='levels',
                                verbose_name=_('map package'))


class MapSource(TranslatableGeoModel):
    """
    A map source, images of levels that can be useful as backgrounds for the map editor
    """
    name = models.SlugField(_('source name'), max_length=50, unique=True),
    package = models.ForeignKey('MapPackage', on_delete=models.PROTECT, related_name='sources',
                                verbose_name=_('map package'))
    image = models.FileField(_('source image'), upload_to='mapsources/')
    bottom_left = models.PointField(_('bottom left coordinates'))
    top_right = models.PointField(_('bottom left coordinates'))
