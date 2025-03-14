from django.db import models
from django.utils.translation import gettext_lazy as _

from c3nav import settings
from c3nav.mapdata.models import LocationGroup
from c3nav.mapdata.models.base import TitledMixin
from c3nav.mapdata.models.geometry.space import ObstacleGroup


class Theme(TitledMixin, models.Model):
    """
    A theme
    """
    # TODO: when a theme base colors change we need to bust the cache somehow
    description = models.TextField(verbose_name=_('Description'))
    public = models.BooleanField(default=False, verbose_name=_('Public'))
    high_contrast = models.BooleanField(default=False, verbose_name=_('This is a high-contrast theme'))
    dark = models.BooleanField(default=False, verbose_name=_('This is a dark theme'))
    default = models.BooleanField(default=False, verbose_name=_('This is a default theme'))
    funky = models.BooleanField(default=False, verbose_name=_(
        'Funky (do not persist through a reload when uses chooses this theme)'))

    randomize_primary_color = models.BooleanField(default=False, verbose_name=_('Use random primary color'))

    color_logo = models.TextField(default='', blank=True,
                                  verbose_name=_('Logo color (can be a CSS gradient if you really want it to)'))

    color_css_initial = models.CharField(default='', blank=True, max_length=32, verbose_name=_('CSS initial/background color'))
    color_css_primary = models.CharField(default='', blank=True, max_length=32, verbose_name=_('CSS primary/accent color'))
    color_css_secondary = models.CharField(default='', blank=True, max_length=32, verbose_name=_('CSS secondary/foreground color'))
    color_css_tertiary = models.CharField(default='', blank=True, max_length=32, verbose_name=_('CSS tertiary color'))
    color_css_quaternary = models.CharField(default='', blank=True, max_length=32, verbose_name=_('CSS quaternary color'))
    color_css_quinary = models.CharField(default='', blank=True, max_length=32, verbose_name=_('CSS quinary color'))
    color_css_header_background = models.CharField(default='', blank=True, max_length=32,
                                                   verbose_name=_('CSS header background color'))
    color_css_header_text = models.CharField(default='', blank=True, max_length=32, verbose_name=_('CSS header text color'))
    color_css_header_text_hover = models.CharField(default='', blank=True, max_length=32,
                                                   verbose_name=_('CSS header text hover color'))
    color_css_shadow = models.CharField(default='', blank=True, max_length=32, verbose_name=_('CSS shadow color'))
    color_css_overlay_background = models.CharField(default='', blank=True, max_length=32,
                                                    verbose_name=_('CSS overlay/label background color'))
    color_css_grid = models.CharField(default='', blank=True, max_length=32, verbose_name=_('CSS grid color'))
    color_css_modal_backdrop = models.CharField(default='', blank=True, max_length=32, verbose_name=_('CSS modal backdrop color'))
    color_css_route_dots_shadow = models.CharField(default='', blank=True, max_length=32,
                                                   verbose_name=_('CSS route dots shadow color'))
    extra_css = models.TextField(default='', blank=True, verbose_name=_('Extra CSS'))

    icon_path = models.CharField(default='', blank=True, max_length=255, verbose_name=_('Root path for icon images'))
    leaflet_marker_config = models.TextField(default='', blank=True, verbose_name=_('Leaflet marker config override'))

    color_background = models.CharField(max_length=32, blank=True, verbose_name=_('background color'))
    color_wall_fill = models.CharField(max_length=32, blank=True, verbose_name=_('wall fill color'))
    color_wall_border = models.CharField(max_length=32, blank=True, verbose_name=_('wall border color'))
    color_door_fill = models.CharField(max_length=32, blank=True, verbose_name=_('door fill color'))
    color_ground_fill = models.CharField(max_length=32, blank=True, verbose_name=_('ground fill color'))
    color_obstacles_default_fill = models.CharField(max_length=32, blank=True, verbose_name=_('default fill color for obstacles'))
    color_obstacles_default_border = models.CharField(max_length=32, blank=True,
                                                      verbose_name=_('default border color for obstacles'))

    last_updated = models.DateTimeField(auto_now=True)

    def css_vars(self):
        return {
            'initial': self.color_css_initial,
            'primary': self.color_css_primary,
            'secondary': self.color_css_secondary,
            'tertiary': self.color_css_tertiary,
            'quaternary': self.color_css_quaternary,
            'quinary': self.color_css_quinary,
            'header-background': self.color_css_header_background,
            'header-text': self.color_css_header_text,
            'header-text-hover': self.color_css_header_text_hover,
            'shadow': self.color_css_shadow,
            'overlay-background': self.color_css_overlay_background,
            'grid': self.color_css_grid,
            'modal-backdrop': self.color_css_modal_backdrop,
            'route-dots-shadow': self.color_css_route_dots_shadow,
            'leaflet-background': self.color_background,
            'logo': self.color_logo,
        }

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

    def pre_save_changed_geometries(self):
        self.location_group.register_changed_geometries()

    def save(self, *args, **kwargs):
        self.pre_save_changed_geometries()
        super().save(*args, **kwargs)

    def pre_delete_changed_geometries(self):
        self.location_group.register_changed_geometries()

    def delete(self, *args, **kwargs):
        self.pre_delete_changed_geometries()
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
