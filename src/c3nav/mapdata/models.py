import json
import os

from django.conf import settings
from django.db import models, transaction
from django.utils.translation import ugettext_lazy as _
from django.dispatch import receiver
from django.core.files.storage import FileSystemStorage

from parler.models import TranslatedFields, TranslatableModel


class MapPackage(models.Model):
    """
    A c3nav map package
    """
    name = models.CharField(_('package identifier'), unique=True, max_length=50,
                            help_text=_('e.g. de.c3nav.33c3.base'))

    bottom = models.DecimalField(_('bottom coordinate'), null=True, max_digits=6, decimal_places=2)
    left = models.DecimalField(_('left coordinate'), null=True, max_digits=6, decimal_places=2)
    top = models.DecimalField(_('top coordinate'), null=True, max_digits=6, decimal_places=2)
    right = models.DecimalField(_('right coordinate'), null=True, max_digits=6, decimal_places=2)


class MapLevel(models.Model):
    """
    A map level (-1, 0, 1, 2…)
    """
    name = models.CharField(_('level name'), max_length=50, unique=True,
                            help_text=_('Usually just an integer (e.g. -1, 0, 1, 2)'))
    altitude = models.DecimalField(_('level altitude'), null=True, max_digits=6, decimal_places=2)
    package = models.ForeignKey('MapPackage', on_delete=models.CASCADE, related_name='levels',
                                verbose_name=_('map package'))

    class Meta:
        ordering = ['altitude']


class MapSourceImageStorage(FileSystemStorage):
    def get_available_name(self, name, *args, max_length=None, **kwargs):
        if self.exists(name):
            os.remove(os.path.join(settings.MEDIA_ROOT, name))
        return super().get_available_name(name, *args, max_length, **kwargs)


def map_source_filename(instance, filename):
    return os.path.join('mapsources', '%s.%s' % (instance.name, filename.split('.')[-1]))


class MapSource(models.Model):
    """
    A map source, images of levels that can be useful as backgrounds for the map editor
    """
    name = models.SlugField(_('source name'), max_length=50, unique=True)
    package = models.ForeignKey('MapPackage', on_delete=models.CASCADE, related_name='sources',
                                verbose_name=_('map package'))

    image = models.FileField(_('source image'), max_length=70,
                             upload_to=map_source_filename, storage=MapSourceImageStorage())

    bottom = models.DecimalField(_('bottom coordinate'), max_digits=6, decimal_places=2)
    left = models.DecimalField(_('left coordinate'), max_digits=6, decimal_places=2)
    top = models.DecimalField(_('top coordinate'), max_digits=6, decimal_places=2)
    right = models.DecimalField(_('right coordinate'), max_digits=6, decimal_places=2)

    @classmethod
    def max_bounds(cls):
        result = cls.objects.all().aggregate(models.Min('bottom'), models.Min('left'),
                                             models.Max('top'), models.Max('right'))
        return ((float(result['bottom__min']), float(result['left__min'])),
                (float(result['top__max']), float(result['right__max'])))

    @property
    def bounds(self):
        return ((self.bottom, self.left), (self.top, self.right))

    @property
    def jsbounds(self):
        return json.dumps(((float(self.bottom), float(self.left)), (float(self.top), float(self.right))))


@receiver(models.signals.post_delete, sender=MapSource)
def delete_image_on_mapsource_delete(sender, instance, **kwargs):
    transaction.on_commit(lambda: instance.image.delete(save=False))


@receiver(models.signals.pre_save, sender=MapSource)
def delete_image_on_mapsource_change(sender, instance, **kwargs):
    if not instance.pk:
        return False

    try:
        old_file = MapSource.objects.get(pk=instance.pk).image
    except MapSource.DoesNotExist:
        return False

    new_file = instance.image

    if map_source_filename(instance, new_file.name) != old_file.name:
        transaction.on_commit(lambda: old_file.delete(save=False))


class MapFeature(TranslatableModel):
    """
    A map feature
    """
    TYPES = (
        ('building', _('Building')),
        ('room', _('Room')),
        ('obstacle', _('Obstacle')),
    )

    name = models.CharField(_('feature identifier'), unique=True, max_length=50, help_text=_('e.g. noc'))
    package = models.ForeignKey('MapPackage', on_delete=models.CASCADE, related_name='features',
                                verbose_name=_('map package'))
    type = models.CharField(max_length=50, choices=TYPES)
    geometry = models.TextField()

    translations = TranslatedFields(
        title=models.CharField(_('package title'), max_length=50),
    )
