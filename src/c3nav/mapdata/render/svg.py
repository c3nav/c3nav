from c3nav.mapdata.utils.svg import SVGImage


def render_svg(level, miny, minx, maxy, maxx, scale=1):
    svg = SVGImage(bounds=((miny, minx), (maxy, maxx)), scale=scale)

    # todo: render

    return svg.get_xml()
