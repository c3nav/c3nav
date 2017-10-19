import pickle

from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from shapely.ops import unary_union

from c3nav.mapdata.models import Level, MapUpdate


class AltitudeAreaGeometries:
    def __init__(self, altitudearea, colors):
        self.geometry = altitudearea.geometry
        self.altitude = altitudearea.altitude
        self.colors = colors


class LevelGeometries:
    def __init__(self):
        self.altitudeareas = []
        self.walls = None
        self.doors = None
        self.holes = None

    @staticmethod
    def crop(self, geometry, crop_to):
        if crop_to is None:
            return geometry
        return geometry.intersection(crop_to)

    @staticmethod
    def rebuild():
        levels = Level.objects.prefetch_related('altitudeareas', 'buildings', 'doors', 'spaces',
                                                'spaces__holes', 'spaces__columns', 'spaces__locationgroups')
        for level in levels:
            geoms = LevelGeometries()
            buildings_geom = unary_union([b.geometry for b in level.buildings.all()])

            for space in level.spaces.all():
                if space.outside:
                    space.geometry = space.geometry.difference(buildings_geom)
                space.geometry = space.geometry.difference(unary_union([c.geometry for c in space.columns.all()]))
                space.holes_geom = unary_union([h.geometry for h in space.holes.all()])
                space.walkable_geom = space.geometry.difference(space.holes_geom)

            spaces_geom = unary_union([s.geometry for s in level.spaces.all()])
            doors_geom = unary_union([d.geometry for d in level.doors.all()])
            walkable_geom = unary_union([s.walkable_geom for s in level.spaces.all()])
            geoms.doors = doors_geom.difference(walkable_geom)
            walkable_geom = walkable_geom.union(geoms.doors)
            if level.on_top_of_id is None:
                geoms.holes = spaces_geom.difference(walkable_geom)

            colors = {}
            for space in level.spaces.all():
                access_restriction = space.access_restriction_id
                colors.setdefault(space.get_color(), {}).setdefault(access_restriction, []).append(space.geometry)
                for area in space.areas.all():
                    access_restriction = area.access_restriction_id or space.access_restriction_id
                    colors.setdefault(area.get_color(), {}).setdefault(access_restriction, []).append(area.geometry)
            colors.pop(None, None)

            for color, color_group in colors.items():
                for access_restriction, areas in tuple(color_group.items()):
                    color_group[access_restriction] = unary_union(areas)

            for altitudearea in level.altitudeareas.all():
                altitudearea_colors = {color: {access_restriction: area.intersection(altitudearea.geometry)
                                               for access_restriction, area in areas.items()
                                               if area.intersects(altitudearea.geometry)}
                                       for color, areas in colors.items()}
                altitudearea_colors = {color: areas for color, areas in altitudearea_colors.items() if areas}
                geoms.altitudeareas.append(AltitudeAreaGeometries(altitudearea, altitudearea_colors))

            geoms.walls = buildings_geom.difference(spaces_geom).difference(doors_geom)
            level.geoms_cache = pickle.dumps(geoms)
            level.save()

        with transaction.atomic():
            for level in levels:
                level.save()


def get_render_level_data(level):
    cache_key = 'mapdata:render_level_data:%s:%s' % (str(level.pk if isinstance(level, Level) else level),
                                                     MapUpdate.cache_key())
    result = cache.get(cache_key, None)
    if result is not None:
        return result

    if isinstance(level, Level):
        level_pk, level_base_altitude = level.pk, level.base_altitude
    else:
        level_pk, level_base_altitude = Level.objects.filter(pk=level).values_list('pk', 'base_altitude')[0]

    levels = Level.objects.filter(Q(on_top_of=level_pk) | Q(base_altitude__lte=level_base_altitude))
    result = tuple((pickle.loads(geoms_cache), default_height)
                   for geoms_cache, default_height in levels.values_list('geoms_cache', 'default_height'))
    cache.set(cache_key, result, 900)

    return result
