import copy

import numpy as np
from django.utils.translation import ugettext_lazy as _

from c3nav.mapdata.models import AreaLocation
from c3nav.mapdata.utils.misc import get_dimensions


class Route:
    def __init__(self, connections, distance=None):
        self.connections = tuple(connections)
        self.distance = sum(connection.distance for connection in self.connections)
        self.from_point = connections[0].from_point
        self.to_point = connections[-1].to_point

        self.routeparts = None

    def __repr__(self):
        return ('<Route (\n    %s\n) distance=%f>' %
                ('\n    '.join(repr(connection) for connection in self.connections), self.distance))

    def create_routeparts(self):
        routeparts = []
        connections = []
        add_connections = []
        level = self.connections[0].from_point.level

        for connection in self.connections:
            connections.append(RouteLine(connection))
            point = connection.to_point
            if point.level and point.level != level:
                if routeparts:
                    routeparts[-1].lines.extend(connections[:1])
                routeparts.append(RoutePart(level, add_connections+connections))
                level = point.level
                add_connections = [copy.copy(line) for line in connections[-3:]]
                connections = []

        if connections or add_connections:
            if routeparts:
                routeparts[-1].lines.extend(connections[:1])
            routeparts.append(RoutePart(level, add_connections+connections))

        routeparts = [routepart for routepart in routeparts if not routepart.level.intermediate]

        for routepart in routeparts:
            routepart.render_svg_coordinates()

        self.describe(routeparts)

        self.routeparts = routeparts

    @staticmethod
    def describe_point(point):
        locations = sorted(AreaLocation.objects.filter(location_type__in=('room', 'level', 'area'),
                                                       name__in=point.arealocations),
                           key=AreaLocation.get_sort_key, reverse=True)

        if not locations:
            return _('Unknown Location'),  _('Unknown Location')
        elif locations[0].location_type == 'level':
            return _('Unknown Location'), locations[0].title
        else:
            return locations[0].title, locations[0].subtitle

    def describe(self, routeparts):
        for i, routepart in enumerate(routeparts):
            for j, line in enumerate(routepart.lines):
                from_room = line.from_point.room
                to_room = line.to_point.room

                if i and not j:
                    line.ignore = True

                line.turning = ''

                if j:
                    line.angle_change = (line.angle - routepart.lines[j - 1].angle + 180) % 360 - 180

                    if 20 < line.angle_change <= 75:
                        line.turning = 'light_right'
                    elif -75 <= line.angle_change < -20:
                        line.turning = 'light_left'
                    elif 75 < line.angle_change:
                        line.turning = 'right'
                    elif line.angle_change < -75:
                        line.turning = 'left'

                line.icon = line.ctype or line.turning

                distance = line.distance

                if from_room is None:
                    line.arrow = True
                    if j+1 < len(routepart.lines) and routepart.lines[j+1].ctype_main == 'elevator':
                        line.ignore = True
                    elif j > 0 and (routepart.lines[j-1].ignore or routepart.lines[j-1].ctype_main == 'elevator'):
                        line.ignore = True
                    else:
                        line.icon = 'location'
                        line.title, line.description = self.describe_point(line.to_point)

                elif line.ctype_main in ('stairs', 'escalator', 'elevator'):
                    line.description = {
                        'stairs_up': _('Go up the stairs.'),
                        'stairs_down': _('Go down the stairs.'),
                        'escalator_up': _('Take the escalator upwards.'),
                        'escalator_down': _('Take the escalator downwards.'),
                        'elevator_up': _('Take the elevator upwards.'),
                        'elevator_down': _('Take the elevator downwards.')
                    }.get(line.ctype)

                    if line.ctype_main == 'elevator':
                        if from_room is None or (to_room is None and from_room.level.level != routepart.level):
                            line.ignore = True
                        line.arrow = False

                elif to_room is None:
                    if from_room is not None and from_room.level.level.intermediate:
                        line.ignore = True

                    if j > 0:
                        if routepart.lines[j-1].ctype_main == 'elevator':
                            line.arrow = False
                            line.ignore = True

                    if j+1 < len(routepart.lines):
                        if routepart.lines[j+1].to_point.room.level.level.intermediate:
                            line.ignore = True

                    if j+2 < len(routepart.lines):
                        if routepart.lines[j+2].ctype_main == 'elevator':
                            line.ignore = True

                    line.description = {
                        'left': _('Go through the door on the left.'),
                        'right': _('Go through the door on the right.'),
                    }.get(line.turning.split('_')[-1], _('Go through the door.'))

                    line.arrow = False

                else:
                    if j > 0:
                        last = routepart.lines[j-1]
                        if last.can_merge_to_next:
                            if last.turning == '' and (line.turning == '' or last.desc_distance < 1):
                                last.ignore = True
                                last.arrow = False
                                distance += last.desc_distance
                            elif last.turning.endswith('right') and line.turning.endswith('right'):
                                last.ignore = True
                                last.arrow = False
                                line.turning = 'right'
                                distance += last.desc_distance
                            elif last.turning.endswith('left') and line.turning.endswith('left'):
                                last.ignore = True
                                last.arrow = False
                                line.turning = 'left'
                                distance += last.desc_distance
                            elif line.turning == '':
                                last.ignore = True
                                last.arrow = False
                                line.turning = last.turning
                                distance += last.desc_distance

                    line.description = {
                        'light_left': _('Turn light to the left and continue for %(d).1f meters.') % {'d': distance},
                        'light_right': _('Turn light to the right and continue for %(d).1f meters.') % {'d': distance},
                        'left': _('Turn left and continue for %(d).1f meters.') % {'d': distance},
                        'right': _('Turn right and continue for %(d).1f meters.') % {'d': distance}
                    }.get(line.turning, _('Continue for %(d).1f meters.') % {'d': distance})

                    if distance < 0.2:
                        line.ignore = True
                    line.can_merge_to_next = True

                line.desc_distance = distance

                # line.ignore = False
                if line.ignore:
                    line.icon = None
                    line.description = None
                    line.desc_distance = None
                    line.can_merge_to_next = False

                if line.arrow is None:
                    line.arrow = not line.ignore

            last_lines = [line for line in routepart.lines if line.ctype_main != 'elevator']
            if len(last_lines) > 1:
                last_lines[-1].arrow = True

            unignored_lines = [i for i, line in enumerate(routepart.lines) if line.description]
            if unignored_lines:
                first_unignored_i = unignored_lines[0]
                if first_unignored_i > 0:
                    first_unignored = routepart.lines[first_unignored_i]
                    point = first_unignored.from_point if first_unignored.from_point.room else first_unignored.to_point

                    line = routepart.lines[first_unignored_i-1]
                    line.ignore = False
                    line.icon = 'location'
                    line.title, line.description = self.describe_point(point)

        last_line = routeparts[-1].lines[-1]
        if last_line.icon == 'location':
            last_line.ignore = True


class RoutePart:
    def __init__(self, graphlevel, lines):
        self.graphlevel = graphlevel
        self.level = graphlevel.level
        self.lines = lines

    def render_svg_coordinates(self):
        svg_width, svg_height = get_dimensions()

        points = (self.lines[0].from_point,) + tuple(connection.to_point for connection in self.lines)
        for point in points:
            point.svg_x = point.x * 6
            point.svg_y = (svg_height - point.y) * 6

        x, y = zip(*((point.svg_x, point.svg_y) for point in points if point.level == self.graphlevel))

        self.distance = sum(connection.distance for connection in self.lines)

        # bounds for rendering
        self.svg_min_x = min(x) - 20
        self.svg_max_x = max(x) + 20
        self.svg_min_y = min(y) - 20
        self.svg_max_y = max(y) + 20

        svg_width = self.svg_max_x - self.svg_min_x
        svg_height = self.svg_max_y - self.svg_min_y

        if svg_width < 150:
            self.svg_min_x -= (10 - svg_width) / 2
            self.svg_max_x += (10 - svg_width) / 2

        if svg_height < 150:
            self.svg_min_y += (10 - svg_height) / 2
            self.svg_max_y -= (10 - svg_height) / 2

        self.svg_width = self.svg_max_x - self.svg_min_x
        self.svg_height = self.svg_max_y - self.svg_min_y

    def __str__(self):
        return repr(self.__dict__)


class RouteLine:
    def __init__(self, connection):
        self.from_point = connection.from_point
        self.to_point = connection.to_point
        self.distance = connection.distance
        self.ctype = connection.ctype
        self.angle = connection.angle

        self.ctype_main = self.ctype.split('_')[0]
        self.ctype_direction = self.ctype.split('_')[-1]

        self.ignore = False
        self.arrow = None
        self.angle_change = None
        self.can_merge_to_next = False

        self.icon = None
        self.title = None
        self.description = None


class NoRoute:
    distance = np.inf
