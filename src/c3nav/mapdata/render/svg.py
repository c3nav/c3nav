from shapely.geometry import box

from c3nav.mapdata.render.base import get_render_level_data
from c3nav.mapdata.utils.svg import SVGImage


def render_svg(level, miny, minx, maxy, maxx, scale=1):
    svg = SVGImage(bounds=((miny, minx), (maxy, maxx)), scale=scale, buffer=1)

    within_coords = (minx-1, miny-1, maxx+1, maxy+1)
    bbox = box(*within_coords)

    render_level_data = get_render_level_data(level)

    crop_to = None
    primary_level_count = 0
    for geoms, default_height in reversed(render_level_data):
        if geoms.holes is not None:
            primary_level_count += 1

        geoms.crop_to = crop_to if primary_level_count > 1 else None

        if geoms.holes is not None:
            if crop_to is None:
                crop_to = geoms.holes
            else:
                crop_to = crop_to.intersection(geoms.holes)

    for geoms, default_height in render_level_data:
        crop_to = bbox
        if geoms.crop_to is not None:
            crop_to = crop_to.intersection(geoms.crop_to)

        for altitudearea_geom, altitude in geoms.altitudeareas:
            svg.add_geometry(crop_to.intersection(altitudearea_geom), fill_color='#eeeeee', altitude=altitude)

        svg.add_geometry(crop_to.intersection(geoms.walls),
                         fill_color='#aaaaaa', stroke_px=0.5, stroke_color='#aaaaaa', elevation=default_height)

        svg.add_geometry(crop_to.intersection(geoms.doors), fill_color='#ffffff', elevation=0)

    return svg
