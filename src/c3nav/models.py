from django.contrib.gis.db import models
from django.contrib.gis.db.models.query import GeoQuerySet

from parler.managers import TranslatableManager, TranslatableQuerySet
from parler.models import TranslatableModel


class TranslatableGeoQuerySet(TranslatableQuerySet, GeoQuerySet):
    pass


class TranslatableGeoManager(TranslatableManager):
    queryset_class = TranslatableGeoQuerySet


class TranslatableGeoModel(TranslatableModel, models.Model):
    objects = TranslatableGeoManager()

    class Meta:
        abstract = True
