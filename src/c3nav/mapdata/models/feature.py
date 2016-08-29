from django.db import models
from django.utils.translation import ugettext_lazy as _

from parler.models import TranslatedFields, TranslatableModel


class Feature(TranslatableModel):
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

    translations = TranslatedFields(
        title=models.CharField(_('package title'), max_length=50),
    )
