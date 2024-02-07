from django.db import models
from django.utils.translation import gettext_lazy as _

from c3nav.mapdata.models import LocationGroup
from c3nav.mapdata.models.base import TitledMixin
from c3nav.mapdata.models.geometry.space import ObstacleGroup


class Theme(TitledMixin, models.Model):
    """
    A theme
    """
    # TODO: when a theme base colors change we need to bust the cache somehow
    description = models.TextField(verbose_name=('Description'))
    public = models.BooleanField(default=False, verbose_name=_('Public'))
    color_background = models.CharField(max_length=32, verbose_name=_('background color'))
    color_wall_fill = models.CharField(max_length=32, verbose_name=_('wall fill color'))
    color_wall_border = models.CharField(max_length=32, verbose_name=_('wall border color'))
    color_door_fill = models.CharField(max_length=32, verbose_name=_('door fill color'))
    color_ground_fill = models.CharField(max_length=32, verbose_name=_('ground fill color'))
    color_obstacles_default_fill = models.CharField(max_length=32, verbose_name=_('default fill color for obstacles'))
    color_obstacles_default_border = models.CharField(max_length=32,
                                                      verbose_name=_('default border color for obstacles'))

    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Theme')
        verbose_name_plural = _('Themes')
        default_related_name = 'themes'


class ThemeLocationGroupBackgroundColor(models.Model):
    """
    A background color for a LocationGroup in a theme
    """
    theme = models.ForeignKey(Theme, on_delete=models.CASCADE, related_name="location_groups")
    location_group = models.ForeignKey(LocationGroup, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name="theme_colors")
    fill_color = models.CharField(max_length=32, null=True, blank=True)
    border_color = models.CharField(max_length=32, null=True, blank=True)

    def save(self, *args, **kwargs):
        self.location_group.register_changed_geometries()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self.location_group.register_changed_geometries()
        super().delete(*args, **kwargs)


class ThemeObstacleGroupBackgroundColor(models.Model):
    """
    A background color for an ObstacleGroup in a theme
    """
    theme = models.ForeignKey(Theme, on_delete=models.CASCADE, related_name="obstacle_groups")
    obstacle_group = models.ForeignKey(ObstacleGroup, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name="theme_colors")
    fill_color = models.CharField(max_length=32, null=True, blank=True)
    border_color = models.CharField(max_length=32, null=True, blank=True)
