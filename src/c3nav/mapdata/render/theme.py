from c3nav import settings
from c3nav.mapdata.models.geometry.space import ObstacleGroup
from c3nav.mapdata.models.locations import LocationTag
from c3nav.mapdata.models.theme import Theme

RENDER_COLOR_BACKGROUND = "#DCDCDC"
RENDER_COLOR_WALL_FILL = "#aaaaaa"
RENDER_COLOR_WALL_BORDER = "#666666"
RENDER_COLOR_DOOR_FILL = "#ffffff"
RENDER_COLOR_GROUND_FILL = "#eeeeee"
RENDER_COLOR_OBSTACLES_DEFAULT_FILL = "#b7b7b7"
RENDER_COLOR_OBSTACLES_DEFAULT_BORDER = "#888888"


class ThemeColorManager:
    # TODO: border colors are not implemented yet?
    # todo: get rid of this eventually, make it a contextmanager
    def __init__(self, theme: Theme = None):
        self.theme_id = theme.pk if theme is not None else 0
        if theme is None:
            self.background = settings.BASE_THEME['map']['background']
            self.wall_fill = settings.BASE_THEME['map']['wall_fill']
            self.wall_border = settings.BASE_THEME['map']['wall_border']
            self.door_fill = settings.BASE_THEME['map']['door_fill']
            self.ground_fill = settings.BASE_THEME['map']['ground_fill']
            self.obstacles_default_fill = settings.BASE_THEME['map']['obstacles_default_fill']
            self.obstacles_default_border = settings.BASE_THEME['map']['obstacles_default_border']
            self.highlight = settings.BASE_THEME['map']['highlight']
            self.location_tag_border_colors = {}
            self.location_tag_fill_colors = {
                tag.pk: tag.color for tag in LocationTag.objects.filter(color__isnull=False).all()
            }
            self.obstacle_group_border_colors = {}
            self.obstacle_group_fill_colors = {
                obstacle_group.pk: obstacle_group.color
                for obstacle_group in ObstacleGroup.objects.filter(color__isnull=False).all()
            }
        else:
            self.background = theme.color_background or settings.BASE_THEME['map']['background']
            self.wall_fill = theme.color_wall_fill or settings.BASE_THEME['map']['wall_fill']
            self.wall_border = theme.color_wall_border or settings.BASE_THEME['map']['wall_border']
            self.door_fill = theme.color_door_fill or settings.BASE_THEME['map']['door_fill']
            self.ground_fill = theme.color_ground_fill or settings.BASE_THEME['map']['ground_fill']
            self.obstacles_default_fill = theme.color_obstacles_default_fill or settings.BASE_THEME['map']['obstacles_default_fill']
            self.obstacles_default_border = theme.color_obstacles_default_border or settings.BASE_THEME['map']['obstacles_default_border']
            self.highlight = theme.color_css_primary or settings.BASE_THEME['map']['highlight']
            self.location_tag_border_colors = {
                theme_tag.tag_id: theme_tag.border_color
                for theme_tag in theme.tags.all()
            }
            self.location_tag_fill_colors = {
                theme_tag.tag_id: theme_tag.fill_color
                for theme_tag in theme.tags.all()
            }
            self.obstacle_group_border_colors = {
                theme_obstacle_group.obstacle_group_id: theme_obstacle_group.border_color
                for theme_obstacle_group in theme.obstacle_groups.all()
            }
            self.obstacle_group_fill_colors = {
                theme_obstacle.obstacle_group_id: theme_obstacle.fill_color
                for theme_obstacle in theme.obstacle_groups.all()
            }

    def location_border_color(self, location: LocationTag):
        return self.location_tag_border_colors.get(location.pk, None)

    def location_tag_fill_color(self, location: LocationTag):
        return self.location_tag_fill_colors.get(location.pk, None)

    def obstaclegroup_border_color(self, obstacle_group: ObstacleGroup):
        return self.obstacle_group_border_colors.get(obstacle_group.pk, self.obstacles_default_border)

    def obstaclegroup_fill_color(self, obstacle_group: ObstacleGroup):
        return self.obstacle_group_fill_colors.get(obstacle_group.pk, self.obstacles_default_fill)


class ColorManager:
    themes = {}
    default_theme = None
    cache_key = None

    @classmethod
    def for_theme(cls, theme):
        from c3nav.mapdata.models import MapUpdate
        current_cache_key = MapUpdate.last_update().cache_key
        if cls.cache_key != current_cache_key:
            cls.default_theme = None
            cls.themes = {}
            cls.cache_key = current_cache_key
        if theme is None:
            if cls.default_theme is None:
                cls.default_theme = ThemeColorManager()
            return cls.default_theme
        if not isinstance(theme, Theme):
            theme = Theme.objects.get(pk=theme)
        if theme.pk not in cls.themes:
            cls.themes[theme.pk] = ThemeColorManager(theme)
        return cls.themes[theme.pk]

    @classmethod
    def refresh(cls):
        cls.themes.clear()
