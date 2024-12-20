import json

from django.core.serializers.json import DjangoJSONEncoder


def _preencode(data, magic_marker, in_coords=False, in_groups=False):
    if isinstance(data, dict):
        data = data.copy()
        for name, value in tuple(data.items()):
            if name in ('bounds', 'point', 'locations') and isinstance(value, (tuple, list)):
                data[name] = magic_marker+json.dumps(value, cls=DjangoJSONEncoder)+magic_marker
            else:
                data[name] = _preencode(value, magic_marker,
                                        in_coords=(name == 'coordinates'), in_groups=(name == 'groups'))
        return data
    elif isinstance(data, (tuple, list)):
        if (in_coords and data and isinstance(data[0], (int, float))) or in_groups:
            return magic_marker+json.dumps(data, cls=DjangoJSONEncoder)+magic_marker
        else:
            return tuple(_preencode(value, magic_marker, in_coords) for value in data)
    else:
        return data


def json_encoder_reindent(method, data, *args, **kwargs):
    magic_marker = '***JSON_MAGIC_MARKER***'
    test_encode = json.dumps(data, cls=DjangoJSONEncoder)
    while magic_marker in test_encode:
        magic_marker += '*'
    result = method(_preencode(data, magic_marker), *args, **kwargs)
    if type(result) == str:
        return result.replace('"'+magic_marker, '').replace(magic_marker+'"', '')
    else:
        magic_marker = magic_marker.encode()
        return result.replace(b'"'+magic_marker, b'').replace(magic_marker+b'"', b'')


def format_geojson(data, rounded=True):
    coordinates = data.get('coordinates', None)
    if coordinates is not None:
        if data['type'] == 'Point':
            coordinates = tuple(round(i, 2) for i in coordinates)
        elif data['type'] == 'LineString' or data['type'] == 'MultiPoint':
            coordinates = round_coordinates(coordinates)
        elif data['type'] == 'MultiLineString':
            coordinates = tuple(round_coordinates(linestring) for linestring in coordinates)
        elif data['type'] == 'Polygon':
            coordinates = round_polygon(coordinates)
            if not coordinates:
                data['type'] = 'MultiPolygon'
        elif data['type'] == 'MultiPolygon':
            coordinates = round_multipolygon(coordinates)
        else:
            raise ValueError('Unknown geojson type: %s' % data['type'])
        return {
            'type': data['type'],
            'coordinates': coordinates,
        }
    return {
        'type': data['type'],
        'geometries': [format_geojson(geometry, rounded=rounded) for geometry in data['geometries']],
    }


def round_multipolygon(coordinates):
    # round every polygon on its own, then remove empty polygons
    coordinates = tuple(round_polygon(polygon) for polygon in coordinates)
    return tuple(polygon for polygon in coordinates if polygon)


def check_ring(coordinates):
    # check if this is a valid ring
    # that measn it has at least 3 points (or 4 if the first and last one are identical)
    return len(coordinates) >= (4 if coordinates[0] == coordinates[-1] else 3)


def round_polygon(coordinates):
    # round each ring on it's own and remove rings that are invalid
    # if the exterior ring is invalid, return and empty polygon
    coordinates = tuple(round_coordinates(ring) for ring in coordinates)
    if not coordinates:
        return coordinates
    exterior, *interiors = coordinates
    if not check_ring(exterior):
        return ()
    return (exterior, *(interior for interior in interiors if check_ring(interior)))


def round_coordinates(coordinates):
    # round coordinates, as in a list of x,y tuples
    # filter out consecutive identical points
    result = []
    last_point = None
    for x, y in coordinates:
        point = (round(x, 2), round(y, 2))
        if point == last_point:
            continue
        result.append(point)
        last_point = point
    return result
