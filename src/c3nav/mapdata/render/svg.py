from django.db.models import Prefetch, Q
from shapely.geometry import box
from shapely.ops import unary_union

from c3nav.mapdata.models import AltitudeArea, Building, Door, Level, Space
from c3nav.mapdata.utils.svg import SVGImage


def render_svg(level, miny, minx, maxy, maxx, scale=1):
    svg = SVGImage(bounds=((miny, minx), (maxy, maxx)), scale=scale)

    within_coords = (minx-1, miny-1, maxx+1, maxy+1)
    bbox = box(*within_coords)

    levels = Level.objects.filter(Q(on_top_of=level.pk) | Q(base_altitude__lte=level.base_altitude))
    levels = levels.prefetch_related(Prefetch('altitudeareas', AltitudeArea.objects.within(*within_coords)),
                                     Prefetch('buildings', Building.objects.within(*within_coords)),
                                     Prefetch('spaces', Space.objects.within(*within_coords)),
                                     Prefetch('doors', Door.objects.within(*within_coords)))

    for level in levels:
        buildings_geom = bbox.intersection(unary_union([b.geometry for b in level.buildings.all()]))
        # svg.add_geometry(buildings_geom, fill_color='#aaaaaa')

        for altitudearea in level.altitudeareas.all():
            svg.add_geometry(bbox.intersection(altitudearea.geometry),
                             fill_color='#ffffff', altitude=altitudearea.altitude)

        for space in level.spaces.all():
            if space.outside:
                space.geometry = space.geometry.difference(buildings_geom)

        spaces_geom = bbox.intersection(unary_union([s.geometry for s in level.spaces.all()]))
        doors_geom = bbox.intersection(unary_union([d.geometry for d in level.doors.all()]))

        svg.add_geometry(spaces_geom, fill_color='#eeeeee')
        # svg.add_geometry(doors_geom.difference(spaces_geom), fill_color='#ffffff')

        walls_geom = buildings_geom.difference(spaces_geom).difference(doors_geom)

        svg.add_geometry(walls_geom, fill_color='#aaaaaa', stroke_px=0.5, stroke_color='#aaaaaa',
                         elevation=level.default_height)

    return svg.get_xml()
