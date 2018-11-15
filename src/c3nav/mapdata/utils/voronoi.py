import math
from itertools import chain

from shapely.geometry import JOIN_STYLE, Polygon, box
from shapely.ops import unary_union

import pyvoronoi


class PolygonVoronoi:
    def __init__(self):
        self._polygons = {}
        self._simplified_polygons = {}

    def add_polygon(self, key, polygon: Polygon):
        self._polygons[key] = polygon

    def calculate(self):
        pv = pyvoronoi.Pyvoronoi(100)
        outside = box(*unary_union(tuple(self._polygons.values())).bounds).buffer(10, join_style=JOIN_STYLE.mitre)
        segment_to_polygon = []
        for i, polygon in enumerate(chain(self._polygons.values(), [outside])):
            for ring in (polygon.exterior, *polygon.interiors):
                pv.AddSegment([list(coords) for coords in ring.coords])
                # for from_point, to_point in zip(ring.coords[:-1], ring.coords[1:]):
                #    pv.AddSegment([list(from_point), list(to_point)])
                segment_to_polygon.append(i)

        pv.Construct()
        vertices = tuple((v.X, v.Y) for v in pv.GetVertices())

        polygon_patches = {i: [] for i in range(len(self._polygons))}
        for cell in pv.GetCells():
            if cell.is_open or cell.is_degenerate:
                continue

            coords = [vertices[i] for i in cell.vertices]
            if not all(math.isfinite(c) for c in chain(*coords)):
                continue
            patch = Polygon(coords).buffer(0)
            if patch.is_empty or not patch.is_valid:
                continue
            polygon_i = segment_to_polygon[cell.site]
            if polygon_i in polygon_patches:
                polygon_patches[polygon_i].append(patch)

        svg = """<?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">
        <svg xmlns="http://www.w3.org/2000/svg"
            xmlns:xlink="http://www.w3.org/1999/xlink"
            version="1.1" baseProfile="full"
            width="500" height="500">"""

        for i, patches in polygon_patches.items():
            if len(patches):
                print('\n\n')
                for patch in patches:
                    print(patch)
                print(patches)
                svg += unary_union(patches).svg().replace(' stroke="#555555" stroke-width="2.0"', '')

        for polygon in self._polygons.values():
            svg += polygon.svg().replace(' stroke="#555555" stroke-width="2.0"', '')

        svg += "</svg>"

        open('test.svg', 'w').write(svg)
