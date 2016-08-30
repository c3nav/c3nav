from django.db import models
from django.utils.translation import ugettext_lazy as _


class Feature(models.Model):
    """
    A map feature
    """
    TYPES = (
        ('building', _('Building')),
        ('room', _('Room')),
        ('obstacle', _('Obstacle')),
    )

    name = models.CharField(_('feature identifier'), unique=True, max_length=50, help_text=_('e.g. noc'))
    package = models.ForeignKey('Package', on_delete=models.CASCADE, related_name='features',
                                verbose_name=_('map package'))
    type = models.CharField(max_length=50, choices=TYPES)
    geometry = models.TextField()


class FeatureTitle(models.Model):
    feature = models.ForeignKey('Feature', on_delete=models.CASCADE, related_name='titles',
                                verbose_name=_('map package'))
    language = models.CharField(max_length=50)
    title = models.CharField(max_length=50)

    class Meta:
        unique_together = ('feature', 'language')
