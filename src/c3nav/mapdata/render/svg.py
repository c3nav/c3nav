from django.db.models import Prefetch, Q
from shapely.geometry import box
from shapely.ops import unary_union

from c3nav.mapdata.models import AltitudeArea, Building, Door, Level, Space
from c3nav.mapdata.utils.svg import SVGImage


def render_svg(level, miny, minx, maxy, maxx, scale=1):
    svg = SVGImage(bounds=((miny, minx), (maxy, maxx)), scale=scale, buffer=2)

    within_coords = (minx-2, miny-2, maxx+2, maxy+2)
    bbox = box(*within_coords)

    levels = Level.objects.filter(Q(on_top_of=level.pk) | Q(base_altitude__lte=level.base_altitude))
    levels = levels.prefetch_related(Prefetch('altitudeareas', AltitudeArea.objects.within(*within_coords)),
                                     Prefetch('buildings', Building.objects.within(*within_coords)),
                                     Prefetch('doors', Door.objects.within(*within_coords)),
                                     Prefetch('spaces', Space.objects.within(*within_coords).prefetch_related(
                                         'holes', 'columns'
                                     )))

    for level in levels:
        buildings_geom = bbox.intersection(unary_union([b.geometry for b in level.buildings.all()]))
        # svg.add_geometry(buildings_geom, fill_color='#aaaaaa')

        for space in level.spaces.all():
            if space.outside:
                space.geometry = space.geometry.difference(buildings_geom)
            space.geometry = space.geometry.difference(unary_union([c.geometry for c in space.columns.all()]))
            space.holes_geom = unary_union([h.geometry for h in space.holes.all()])
            space.walkable_geom = space.geometry.difference(space.holes_geom)

        spaces_geom = bbox.intersection(unary_union([s.geometry for s in level.spaces.all()]))
        doors_geom = bbox.intersection(unary_union([d.geometry for d in level.doors.all()]))
        walkable_geom = unary_union([w.walkable_geom for w in level.spaces.all()]).union(doors_geom)

        for altitudearea in level.altitudeareas.all():
            svg.add_geometry(bbox.intersection(altitudearea.geometry).intersection(walkable_geom),
                             fill_color='#eeeeee', altitude=altitudearea.altitude)

        spaces_geom = bbox.intersection(unary_union([s.geometry for s in level.spaces.all()]))
        doors_geom = bbox.intersection(unary_union([d.geometry for d in level.doors.all()]))

        walls_geom = buildings_geom.difference(spaces_geom).difference(doors_geom)

        svg.add_geometry(walls_geom, fill_color='#aaaaaa', stroke_px=0.5, stroke_color='#aaaaaa',
                         elevation=level.default_height)

        svg.add_geometry(doors_geom, fill_color='#ffffff', elevation=0)

    return svg
