import math
from collections import deque, namedtuple
from itertools import chain
from typing import List, Sequence, Union

from django.core import checks
from django.utils.functional import cached_property
from shapely import prepared, speedups
from shapely.geometry import GeometryCollection, LinearRing, LineString, MultiLineString, MultiPolygon, Point, Polygon
from shapely.geometry import mapping as shapely_mapping
from shapely.geometry import shape as shapely_shape

if speedups.available:
    speedups.enable()


@checks.register()
def check_speedups(app_configs, **kwargs):
    errors = []
    if not speedups.available:
        errors.append(
            checks.Warning(
                'Your shapely version does not have speedups enabled. This will significantly slow down c3nav!',
                obj='shapely.speedups',
                id='c3nav.mapdata.W001',
            )
        )
    return errors


class WrappedGeometry():
    wrapped_geojson = None

    def __init__(self, geojson):
        self.wrapped_geojson = geojson

    @cached_property
    def wrapped_geom(self):
        if not self.wrapped_geojson or not self.wrapped_geojson['coordinates']:
            return GeometryCollection()
        return shapely_shape(self.wrapped_geojson)

    def __getattr__(self, name):
        return getattr(self.wrapped_geom, name)

    @property
    def __class__(self):
        return self.wrapped_geom.__class__

    def __reduce__(self):
        return WrappedGeometry, (self.wrapped_geojson, )


def unwrap_geom(geometry):
    return geometry.wrapped_geom if isinstance(geometry, WrappedGeometry) else geometry


def smart_mapping(geometry):
    if hasattr(geometry, 'wrapped_geojson'):
        return geometry.wrapped_geojson
    return shapely_mapping(geometry)


def clean_geometry(geometry):
    """
    if the given geometry is a Polygon and invalid, try to make it valid if it results in a Polygon (not MultiPolygon)
    """
    if geometry.is_valid:
        return geometry

    if isinstance(geometry, Polygon):
        return geometry.buffer(0)

    return geometry


def assert_multipolygon(geometry: Polygon | MultiPolygon | GeometryCollection) -> list[Polygon]:
    """
    given a Polygon or a MultiPolygon, return a list of Polygons
    :param geometry: a Polygon or a MultiPolygon
    :return: a list of Polygons
    """
    if geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    return [geom for geom in geometry.geoms if isinstance(geom, Polygon)]


def assert_multilinestring(geometry: LineString | MultiLineString | GeometryCollection) -> list[LineString]:
    """
    given a LineString or MultiLineString, return a list of LineStrings
    :param geometry: a LineString or a MultiLineString
    :return: a list of LineStrings
    """
    if geometry.is_empty:
        return []
    if isinstance(geometry, LineString):
        return [geometry]
    return [geom for geom in geometry.geoms if isinstance(geom, LineString)]


def good_representative_point(geometry):
    if isinstance(geometry, Point):
        return geometry
    c = geometry.centroid
    if not isinstance(geometry, (Polygon, MultiPolygon)):
        return geometry.representative_point()
    for polygon in assert_multipolygon(geometry):
        if Polygon(polygon.exterior.coords).contains(c):
            return c
    x1, y1, x2, y2 = geometry.bounds
    lines = (tuple(assert_multilinestring(LineString(((x1, c.y), (x2, c.y))).intersection(unwrap_geom(geometry)))) +
             tuple(assert_multilinestring(LineString(((c.x, y1), (c.x, y2))).intersection(unwrap_geom(geometry)))))
    return min(lines, key=lambda line: (line.distance(c), line.length),
               default=geometry.representative_point()).centroid


def plot_geometry(geom, title=None, bounds=None):
    # these imports live here so they are only imported when needed
    import matplotlib.pyplot as plt
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path

    fig = plt.figure()
    axes = fig.add_subplot(111)
    if bounds is None:
        bounds = geom.bounds
    axes.set_xlim(bounds[0], bounds[2])
    axes.set_ylim(bounds[1], bounds[3])
    verts = []
    codes = []
    if not isinstance(geom, (tuple, list)):
        geom = assert_multipolygon(geom)
    else:
        geom = tuple(chain(*(assert_multipolygon(g) for g in geom)))
    for polygon in geom:
        for ring in chain([polygon.exterior], polygon.interiors):
            verts.extend(ring.coords)
            codes.append(Path.MOVETO)
            codes.extend((Path.LINETO,) * len(ring.coords))
            verts.append(verts[-1])

    if title is not None:
        plt.title(title)

    path = Path(verts, codes)
    patch = PathPatch(path)
    axes.add_patch(patch)
    plt.show()


def get_rings(geometry):
    if isinstance(geometry, Polygon):
        return chain((geometry.exterior, ), geometry.interiors)
    try:
        geoms = geometry.geoms
    except AttributeError:
        pass
    else:
        return chain(*(get_rings(geom) for geom in geoms))

    if isinstance(geometry, LinearRing):
        return (geometry, )

    return ()


cutpoint = namedtuple('cutpoint', ('point', 'polygon', 'ring'))


def cut_line_with_point(line: LineString, point: Point):
    distance = line.project(point)
    if distance <= 0 or distance >= line.length:
        return line,
    pointlist = [(point.x, point.y)]
    subdistance = 0
    last = None
    for i, p in enumerate(line.coords):
        if last is not None:
            subdistance += ((p[0]-last[0])**2 + (p[1]-last[1])**2)**0.5
        last = p
        if subdistance >= distance:
            return (LineString(line.coords[:i] + pointlist),
                    LineString(pointlist + line.coords[i+(1 if subdistance == distance else 0):]))


def cut_polygon_with_line(polygon: Union[Polygon, MultiPolygon, Sequence[Polygon]], line: LineString) -> List[Polygon]:
    orig_polygon = assert_multipolygon(polygon) if isinstance(polygon, (MultiPolygon, Polygon)) else polygon
    polygons: List[List[LinearRing]] = []
    # noinspection PyTypeChecker
    for polygon in orig_polygon:
        polygons.append([polygon.exterior, *polygon.interiors])

    # find intersection points between the line and polygon rings
    points = deque()
    line_prep = prepared.prep(line)
    for i, polygon in enumerate(polygons):
        for j, ring in enumerate(polygon):
            if not line_prep.intersects(ring):
                continue
            intersection = ring.intersection(line)
            for item in getattr(intersection, 'geoms', (intersection, )):
                if isinstance(item, Point):
                    points.append(cutpoint(item, i, j))
                elif isinstance(item, LineString):
                    points.append(cutpoint(Point(*item.coords[0]), i, j))
                    points.append(cutpoint(Point(*item.coords[-1]), i, j))
                else:
                    raise ValueError

    # sort the points by distance along the line
    points = deque(sorted(points, key=lambda p: line.project(p.point)))

    if not points:
        return orig_polygon

    # go through all points and cut pair-wise
    last = points.popleft()
    while points:
        current = points.popleft()

        # don't to anything between different polygons
        if current.polygon != last.polygon:
            last = current
            continue

        polygon = polygons[current.polygon]
        segment = cut_line_with_point(cut_line_with_point(line, last.point)[-1], current.point)[0]

        if current.ring != last.ring:
            # connect rings
            ring1 = cut_line_with_point(polygon[last.ring], last.point)
            ring2 = cut_line_with_point(polygon[current.ring], current.point)
            new_ring = LinearRing(ring1[1].coords[:-1] + ring1[0].coords[:-1] + segment.coords[:-1] +
                                  ring2[1].coords[:-1] + ring2[0].coords[:-1] + segment.coords[::-1])
            if current.ring == 0 or last.ring == 0:
                # join an interior with exterior
                new_i = 0
                polygon[0] = new_ring
                interior = current.ring if last.ring == 0 else last.ring
                polygon[interior] = None
                mapping = {interior: new_i}
            else:
                # join two interiors
                new_i = len(polygon)
                mapping = {last.ring: new_i, current.ring: new_i}
                polygon.append(new_ring)
                polygon[last.ring] = None
                polygon[current.ring] = None

            # fix all remaining cut points that refer to the rings we just joined to point the the correct ring
            points = deque((cutpoint(item.point, item.polygon, mapping[item.ring])
                            if (item.polygon == current.polygon and item.ring in mapping) else item)
                           for item in points)
            last = cutpoint(current.point, current.polygon, new_i)
            continue

        # check if this is not a cut through emptyness
        # half-cut polygons are invalid geometry and shapely won't deal with them
        # so we have to do this the complicated way
        ring = cut_line_with_point(polygon[current.ring], current.point)
        ring = ring[0] if len(ring) == 1 else LinearRing(ring[1].coords[:-1] + ring[0].coords[0:])
        ring = cut_line_with_point(ring, last.point)

        point_forwards = ring[1].coords[1]
        point_backwards = ring[0].coords[-2]
        angle_forwards = math.atan2(point_forwards[0] - last.point.x, point_forwards[1] - last.point.y)
        angle_backwards = math.atan2(point_backwards[0] - last.point.x, point_backwards[1] - last.point.y)
        next_segment_point = Point(segment.coords[1])
        angle_segment = math.atan2(next_segment_point.x - last.point.x, next_segment_point.y - last.point.y)

        while angle_forwards <= angle_backwards:
            angle_forwards += 2*math.pi
        if angle_segment < angle_backwards:
            while angle_segment < angle_backwards:
                angle_segment += 2*math.pi
        else:
            while angle_segment > angle_forwards:
                angle_segment -= 2*math.pi

        # if we cut through emptiness, continue
        if not (angle_backwards < angle_segment < angle_forwards):
            last = current
            continue

        # split ring
        new_i = len(polygons)
        old_ring = LinearRing(ring[0].coords[:-1] + segment.coords[0:])
        new_ring = LinearRing(ring[1].coords[:-1] + segment.coords[::-1])

        # if this is not an exterior cut but creates a new polygon inside a hole,
        # make sure that new_ring contains the exterior for the new polygon
        if current.ring != 0 and not new_ring.is_ccw:
            new_ring, old_ring = old_ring, new_ring

        new_geom = Polygon(new_ring)
        polygon[current.ring] = old_ring
        new_polygon = [new_ring]
        polygons.append(new_polygon)
        mapping = {}

        # assign all [other] interiors of the old polygon to one of the two new polygons
        for i, interior in enumerate(polygon[1:], start=1):
            if i == current.ring:
                continue
            if interior is not None and new_geom.contains(interior):
                polygon[i] = None
                mapping[i] = len(new_polygon)
                new_polygon.append(interior)

        # fix all remaining cut points to point to the new polygon if they refer to moved interiors
        points = deque((cutpoint(item.point, new_i, mapping[item.ring])
                        if (item.polygon == current.polygon and item.ring in mapping) else item)
                       for item in points)

        # fix all remaining cut points that refer to the ring we just split to point the the correct new ring
        points = deque((cutpoint(item.point, new_i, 0)
                        if (item.polygon == current.polygon and item.ring == current.ring and
                            not old_ring.contains(item.point)) else item)
                       for item in points)

        last = cutpoint(current.point, new_i, 0)

    result = deque()
    for polygon in polygons:
        polygon = [ring for ring in polygon if ring is not None]
        new_polygon = Polygon(polygon[0], tuple(polygon[1:]))
        result.append(new_polygon)
    return list(result)


def clean_cut_polygon(polygon: Polygon) -> Polygon:
    interiors = []
    interiors.extend(cut_ring(polygon.exterior))
    exteriors = [(i, ring) for (i, ring) in enumerate(interiors) if ring.is_ccw]

    if len(exteriors) != 1:
        raise ValueError('Invalid cut polygon!')
    exterior = interiors[exteriors[0][0]]
    interiors.pop(exteriors[0][0])

    for ring in polygon.interiors:
        interiors.extend(cut_ring(ring))

    return Polygon(exterior, interiors)


def cut_ring(ring: LinearRing) -> List[LinearRing]:
    """
    Cuts a Linearring into multiple linearrings. Useful if the ring intersects with itself.
    An 8-ring would be split into it's two circles for example.
    """
    rings = []
    new_ring = []
    # noinspection PyPropertyAccess
    for point in ring.coords:
        try:
            # check if this point is already part of the ring
            index = new_ring.index(point)
        except ValueError:
            # if not, append it
            new_ring.append(point)
            continue

        # if yes, we got a loop, add it to the result and remove it from new_ring.
        if len(new_ring) > 2+index:
            rings.append(LinearRing(new_ring[index:]+[point]))
        new_ring = new_ring[:index+1]

    return rings
