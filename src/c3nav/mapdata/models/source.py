import json
import os

from django.conf import settings
from django.db import models, transaction
from django.utils.translation import ugettext_lazy as _
from django.dispatch import receiver
from django.core.files.storage import FileSystemStorage


class SourceImageStorage(FileSystemStorage):
    def get_available_name(self, name, *args, max_length=None, **kwargs):
        if self.exists(name):
            os.remove(os.path.join(settings.MEDIA_ROOT, name))
        return super().get_available_name(name, *args, max_length, **kwargs)


def map_source_filename(instance, filename):
    return os.path.join('mapsources', '%s.%s' % (instance.name, filename.split('.')[-1]))


class Source(models.Model):
    """
    A map source, images of levels that can be useful as backgrounds for the map editor
    """
    name = models.SlugField(_('source name'), max_length=50, unique=True)
    package = models.ForeignKey('Package', on_delete=models.CASCADE, related_name='sources',
                                verbose_name=_('map package'))

    image = models.FileField(_('source image'), max_length=70,
                             upload_to=map_source_filename, storage=SourceImageStorage())

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


@receiver(models.signals.post_delete, sender=Source)
def delete_image_on_mapsource_delete(sender, instance, **kwargs):
    transaction.on_commit(lambda: instance.image.delete(save=False))


@receiver(models.signals.pre_save, sender=Source)
def delete_image_on_mapsource_change(sender, instance, **kwargs):
    if not instance.pk:
        return False

    try:
        old_file = Source.objects.get(pk=instance.pk).image
    except Source.DoesNotExist:
        return False

    new_file = instance.image

    if map_source_filename(instance, new_file.name) != old_file.name:
        transaction.on_commit(lambda: old_file.delete(save=False))
