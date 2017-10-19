import pickle

from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from shapely.ops import unary_union

from c3nav.mapdata.models import Level, MapUpdate


class LevelGeometries:
    def __init__(self):
        self.altitudeareas = []
        self.walls = None
        self.doors = None

    @staticmethod
    def rebuild():
        levels = Level.objects.prefetch_related('altitudeareas', 'buildings', 'doors', 'spaces',
                                                'spaces__holes', 'spaces__columns')
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
            geoms.doors = unary_union([d.geometry for d in level.doors.all()])
            walkable_geom = unary_union([s.walkable_geom for s in level.spaces.all()]).union(geoms.doors)

            for altitudearea in level.altitudeareas.all():
                geoms.altitudeareas.append((altitudearea.geometry.intersection(walkable_geom), altitudearea.altitude))

            geoms.walls = buildings_geom.difference(spaces_geom).difference(geoms.doors)
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
    result = levels.values_list('geoms_cache', 'default_height')
    cache.set(cache_key, result, 900)

    return levels
