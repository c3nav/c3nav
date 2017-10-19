import pickle

from shapely.geometry import box

from c3nav.mapdata.render.base import get_render_level_data
from c3nav.mapdata.utils.svg import SVGImage


def render_svg(level, miny, minx, maxy, maxx, scale=1):
    svg = SVGImage(bounds=((miny, minx), (maxy, maxx)), scale=scale, buffer=2)

    within_coords = (minx-2, miny-2, maxx+2, maxy+2)
    bbox = box(*within_coords)

    for geoms_cache, default_height in get_render_level_data(level):
        geoms = pickle.loads(geoms_cache)
        for altitudearea_geom, altitude in geoms.altitudeareas:
            svg.add_geometry(bbox.intersection(altitudearea_geom), fill_color='#eeeeee', altitude=altitude)

        svg.add_geometry(bbox.intersection(geoms.walls),
                         fill_color='#aaaaaa', stroke_px=0.5, stroke_color='#aaaaaa', elevation=default_height)

        svg.add_geometry(bbox.intersection(geoms.doors), fill_color='#ffffff', elevation=0)

    return svg
