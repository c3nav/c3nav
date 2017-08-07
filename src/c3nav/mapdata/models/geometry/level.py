import itertools
from operator import attrgetter, itemgetter

from django.db import models
from django.db.models import F
from django.utils.translation import ugettext_lazy as _
from shapely.affinity import scale
from shapely.geometry import JOIN_STYLE, LineString
from shapely.ops import cascaded_union

from c3nav.mapdata.fields import GeometryField
from c3nav.mapdata.models import Level
from c3nav.mapdata.models.access import AccessRestrictionMixin
from c3nav.mapdata.models.geometry.base import GeometryMixin
from c3nav.mapdata.models.locations import SpecificLocation
from c3nav.mapdata.utils.geometry import assert_multilinestring, assert_multipolygon, clean_geometry


class LevelGeometryMixin(GeometryMixin):
    level = models.ForeignKey('mapdata.Level', on_delete=models.CASCADE, verbose_name=_('level'))

    class Meta:
        abstract = True

    def get_geojson_properties(self, *args, instance=None, **kwargs) -> dict:
        result = super().get_geojson_properties(*args, **kwargs)
        result['level'] = self.level_id
        if hasattr(self, 'get_color'):
            color = self.get_color(instance=instance)
            if color:
                result['color'] = color
        if hasattr(self, 'opacity'):
            result['opacity'] = self.opacity
        return result

    def _serialize(self, level=True, **kwargs):
        result = super()._serialize(**kwargs)
        if level:
            result['level'] = self.level_id
        return result


class Building(LevelGeometryMixin, models.Model):
    """
    The outline of a building on a specific level
    """
    geometry = GeometryField('polygon')

    class Meta:
        verbose_name = _('Building')
        verbose_name_plural = _('Buildings')
        default_related_name = 'buildings'


class Space(SpecificLocation, LevelGeometryMixin, models.Model):
    """
    An accessible space. Shouldn't overlap with spaces on the same level.
    """
    geometry = GeometryField('polygon')
    height = models.DecimalField(_('height'), max_digits=6, decimal_places=2, null=True, blank=True)
    outside = models.BooleanField(default=False, verbose_name=_('only outside of building'))

    class Meta:
        verbose_name = _('Space')
        verbose_name_plural = _('Spaces')
        default_related_name = 'spaces'

    def _serialize(self, geometry=True, **kwargs):
        result = super()._serialize(geometry=geometry, **kwargs)
        result['height'] = None if self.height is None else float(str(self.height))
        return result


class Door(AccessRestrictionMixin, LevelGeometryMixin, models.Model):
    """
    A connection between two spaces
    """
    geometry = GeometryField('polygon')

    class Meta:
        verbose_name = _('Door')
        verbose_name_plural = _('Doors')
        default_related_name = 'doors'


class AltitudeArea(LevelGeometryMixin, models.Model):
    """
    An altitude area
    """
    geometry = GeometryField('multipolygon')
    altitude = models.DecimalField(_('altitude'), null=False, max_digits=6, decimal_places=2)

    class Meta:
        verbose_name = _('Altitude Area')
        verbose_name_plural = _('Altitude Areas')
        default_related_name = 'altitudeareas'

    @classmethod
    def recalculate(cls):
        # collect location areas
        all_areas = []
        space_areas = {}
        spaces = {}
        levels = Level.objects.prefetch_related('buildings', 'doors', 'spaces', 'spaces__columns',
                                                'spaces__obstacles', 'spaces__lineobstacles', 'spaces__holes',
                                                'spaces__stairs', 'spaces__altitudemarkers')
        for level in levels:
            areas = []
            stairs = []

            # collect all accessible areas on this level
            buildings_geom = cascaded_union(tuple(building.geometry for building in level.buildings.all()))
            for space in level.spaces.all():
                space.orig_geometry = space.geometry
                if space.outside:
                    space.geometry = space.geometry.difference(buildings_geom)
                spaces[space.pk] = space
                area = space.geometry
                buffered = space.geometry.buffer(0.0001)
                remove = cascaded_union(tuple(c.geometry for c in space.columns.all()) +
                                        tuple(o.geometry for o in space.obstacles.all()) +
                                        tuple(o.buffered_geometry for o in space.lineobstacles.all()) +
                                        tuple(h.geometry for h in space.holes.all()))
                areas.extend(assert_multipolygon(space.geometry.difference(remove)))
                for stair in space.stairs.all():
                    substairs = tuple(assert_multilinestring(stair.geometry.intersection(buffered).difference(remove)))
                    for substair in substairs:
                        substair.space = space.pk
                    stairs.extend(substairs)

            areas = assert_multipolygon(cascaded_union(areas+list(door.geometry for door in level.doors.all())))
            areas = [AltitudeArea(geometry=area, level=level) for area in areas]

            space_areas.update({space.pk: [] for space in level.spaces.all()})

            # assign spaces to areas
            for area in areas:
                area.spaces = set()
                area.connected_to = []
                for space in level.spaces.all():
                    if area.geometry.intersects(space.geometry):
                        area.spaces.add(space.pk)
                        space_areas[space.pk].append(area)

            # divide areas using stairs
            for stair in stairs:
                for area in space_areas[stair.space]:
                    if not stair.intersects(area.geometry):
                        continue

                    divided = assert_multipolygon(area.geometry.difference(stair.buffer(0.0001)))
                    if len(divided) > 2:
                        raise ValueError
                    area.geometry = divided[0]
                    if len(divided) == 2:
                        new_area = AltitudeArea(geometry=divided[1], level=level)
                        new_area.spaces = set()
                        new_area.connected_to = [area]
                        area.connected_to.append(new_area)
                        areas.append(new_area)
                        original_spaces = area.spaces
                        if len(area.spaces) == 1:
                            new_area.spaces = area.spaces
                            space_areas[next(iter(area.spaces))].append(new_area)
                        else:
                            # update area spaces
                            for subarea in (area, new_area):
                                spaces_before = subarea.spaces
                                subarea.spaces = set(space for space in original_spaces
                                                     if spaces[space].geometry.intersects(subarea.geometry))
                                for space in spaces_before-subarea.spaces:
                                    space_areas[space].remove(subarea)
                                for space in subarea.spaces-spaces_before:
                                    space_areas[space].append(subarea)

                        # update area connections
                        buffer_area = area.geometry.buffer(0.0005, join_style=JOIN_STYLE.mitre)
                        buffer_new_area = new_area.geometry.buffer(0.0005, join_style=JOIN_STYLE.mitre)
                        remove_area_connected_to = []
                        for other_area in area.connected_to:
                            if not buffer_area.intersects(other_area.geometry):
                                new_area.connected_to.append(other_area)
                                remove_area_connected_to.append(other_area)
                                other_area.connected_to.remove(area)
                                other_area.connected_to.append(new_area)
                            elif other_area != new_area and buffer_new_area.intersects(other_area.geometry):
                                new_area.connected_to.append(other_area)
                                other_area.connected_to.append(new_area)

                        for other_area in remove_area_connected_to:
                            area.connected_to.remove(other_area)
                    break
                else:
                    raise ValueError

            # give altitudes to areas
            for space in level.spaces.all():
                for altitudemarker in space.altitudemarkers.all():
                    for area in space_areas[space.pk]:
                        if area.geometry.contains(altitudemarker.geometry):
                            area.altitude = altitudemarker.altitude
                            break
                    else:
                        raise ValueError(space.title)

            all_areas.extend(areas)

        # give temporary ids to all areas
        for area in all_areas:
            area.geometry = clean_geometry(area.geometry)
        areas = [area for area in all_areas if not area.geometry.is_empty]
        for i, area in enumerate(areas):
            area.tmpid = i
        for area in areas:
            area.connected_to = set(area.tmpid for area in area.connected_to)
        for space in space_areas.keys():
            space_areas[space] = set(area.tmpid for area in space_areas[space])
        areas_without_altitude = set(area.tmpid for area in areas if area.altitude is None)

        # connect levels
        from c3nav.mapdata.models import GraphEdge
        edges = GraphEdge.objects.exclude(from_node__space__level=F('to_node__space__level'))
        edges = edges.select_related('from_node', 'to_node')
        node_areas = {}
        area_connections = {}
        for edge in edges:
            for node in (edge.from_node, edge.to_node):
                if node.pk not in node_areas:
                    tmpid = next(tmpid for tmpid in space_areas[node.space_id]
                                 if areas[tmpid].geometry.contains(node.geometry))
                    node_areas[node.pk] = tmpid
            area_connections.setdefault(node_areas[edge.from_node.pk], set()).add(node_areas[edge.to_node.pk])
            area_connections.setdefault(node_areas[edge.to_node.pk], set()).add(node_areas[edge.from_node.pk])

        del_keys = tuple(tmpid for tmpid in area_connections.keys() if tmpid not in areas_without_altitude)
        for tmpid in del_keys:
            del area_connections[tmpid]

        do_continue = True
        while do_continue:
            do_continue = False
            del_keys = []
            for tmpid in area_connections.keys():
                connections = area_connections[tmpid] - areas_without_altitude
                if connections:
                    area = areas[tmpid]
                    other_area = areas[next(iter(connections))]
                    area.altitude = other_area.altitude
                    areas_without_altitude.remove(tmpid)
                    del_keys.append(tmpid)

            if del_keys:
                do_continue = True
                for tmpid in del_keys:
                    del area_connections[tmpid]

        # interpolate altitudes
        while areas_without_altitude:
            # find a area without an altitude that is connected
            # to one with an altitude to start the chain
            chain = []
            for tmpid in areas_without_altitude:
                area = areas[tmpid]
                connected_with_altitude = area.connected_to-areas_without_altitude
                if connected_with_altitude:
                    chain = [next(iter(connected_with_altitude)), tmpid]
                    current = area
                    break
            else:
                # there are no more chains possible
                break

            # continue chain as long as possible
            while True:
                connected_with_altitude = (current.connected_to-areas_without_altitude).difference(chain)
                if connected_with_altitude:
                    # interpolate
                    area = areas[next(iter(connected_with_altitude))]
                    from_altitude = areas[chain[0]].altitude
                    delta_altitude = area.altitude-from_altitude
                    for i, tmpid in enumerate(chain[1:], 1):
                        areas[tmpid].altitude = from_altitude+delta_altitude*i/len(chain)
                    areas_without_altitude.difference_update(chain)
                    break

                connected = current.connected_to.difference(chain)
                if not connected:
                    # end of chain
                    altitude = areas[chain[0]].altitude
                    for i, tmpid in enumerate(chain[1:], 1):
                        areas[tmpid].altitude = altitude
                    areas_without_altitude.difference_update(chain)
                    break

                # continue chain
                current = areas[next(iter(connected))]
                chain.append(current.tmpid)

        # remaining areas which belong to a room that has an altitude somewhere
        for contained_areas in space_areas.values():
            contained_areas_with_altitude = contained_areas - areas_without_altitude
            contained_areas_without_altitude = contained_areas - contained_areas_with_altitude
            if contained_areas_with_altitude and contained_areas_without_altitude:
                altitude_areas = {}
                for tmpid in contained_areas_with_altitude:
                    area = areas[tmpid]
                    altitude_areas.setdefault(area.altitude, []).append(area.geometry)

                for altitude in altitude_areas.keys():
                    altitude_areas[altitude] = cascaded_union(altitude_areas[altitude])
                for tmpid in contained_areas_without_altitude:
                    area = areas[tmpid]
                    area.altitude = min(altitude_areas.items(), key=lambda aa: aa[1].distance(area.geometry))[0]
                areas_without_altitude.difference_update(contained_areas_without_altitude)

        # last fallback: level base_altitude
        for tmpid in areas_without_altitude:
            area = areas[tmpid]
            area.altitude = area.level.base_altitude

        level_areas = {}
        for area in areas:
            level_areas.setdefault(area.level, set()).add(area.tmpid)

        #
        # now fill in the obstacles and so on
        #
        for level in levels:
            for space in level.spaces.all():
                space.geometry = space.orig_geometry

            buildings_geom = cascaded_union(tuple(b.geometry for b in level.buildings.all()))
            doors_geom = cascaded_union(tuple(d.geometry for d in level.doors.all()))
            space_geom = cascaded_union(tuple((s.geometry if not s.outside else s.geometry.difference(buildings_geom))
                                              for s in level.spaces.all()))
            accessible_area = cascaded_union((doors_geom, space_geom))
            for space in level.spaces.all():
                accessible_area = accessible_area.difference(space.geometry.intersection(
                    cascaded_union(tuple(h.geometry for h in space.holes.all()))
                ))

            areas_by_altitude = {}
            for tmpid in level_areas.get(level, []):
                area = areas[tmpid]
                areas_by_altitude.setdefault(area.altitude, []).append(area.geometry.buffer(0.01))
            areas_by_altitude = {altitude: [cascaded_union(alt_areas)]
                                 for altitude, alt_areas in areas_by_altitude.items()}

            accessible_area = accessible_area.difference(
                cascaded_union(tuple(itertools.chain(*areas_by_altitude.values())))
            )

            stairs = []
            for space in level.spaces.all():
                geom = space.geometry
                if space.outside:
                    geom = space_geom.difference(buildings_geom)
                remaining_space = geom.intersection(accessible_area)
                if remaining_space.is_empty:
                    continue

                max_len = ((geom.bounds[0] - geom.bounds[2]) ** 2 + (geom.bounds[1] - geom.bounds[3]) ** 2) ** 0.5
                stairs = []
                for stair in space.stairs.all():
                    for substair in assert_multilinestring(stair.geometry):
                        for coord1, coord2 in zip(tuple(substair.coords)[:-1], tuple(substair.coords)[1:]):
                            line = LineString([coord1, coord2])
                            fact = (max_len * 3) / line.length
                            scaled = scale(line, xfact=fact, yfact=fact)
                            stairs.append(scaled.buffer(0.0001, JOIN_STYLE.mitre).intersection(geom.buffer(0.0001)))
                if stairs:
                    stairs = cascaded_union(stairs)
                    remaining_space = remaining_space.difference(stairs)

                for polygon in assert_multipolygon(remaining_space.buffer(0)):
                    center = polygon.centroid
                    buffered = polygon.buffer(0.001, JOIN_STYLE.mitre)
                    touches = tuple((altitude, buffered.intersection(alt_areas[0]).area)
                                    for altitude, alt_areas in areas_by_altitude.items()
                                    if buffered.intersects(alt_areas[0]))
                    if touches:
                        max_intersection = max(touches, key=itemgetter(1))[1]
                        altitude = max(altitude for altitude, area in touches if area > max_intersection / 2)
                    else:
                        altitude = min(areas_by_altitude.items(), key=lambda a: a[1][0].distance(center))[0]
                    areas_by_altitude[altitude].append(polygon.buffer(0.001, JOIN_STYLE.mitre))

                    # plot_geometry(remaining_space, title=space.title)

            areas_by_altitude = {altitude: cascaded_union(alt_areas)
                                 for altitude, alt_areas in areas_by_altitude.items()}

            level_areas[level] = [AltitudeArea(level=level, geometry=geometry, altitude=altitude)
                                  for altitude, geometry in areas_by_altitude.items()]

        areas = tuple(itertools.chain(*(a for a in level_areas.values())))
        for i, area in enumerate(areas):
            area.tmpid = i
        for level in levels:
            level_areas[level] = set(area.tmpid for area in level_areas.get(level, []))

        # save to database
        from c3nav.mapdata.models import MapUpdate
        with MapUpdate.lock():
            areas_to_save = set(range(len(areas)))

            all_candidates = AltitudeArea.objects.select_related('level')
            for candidate in all_candidates:
                candidate.area = candidate.geometry.area
            all_candidates = sorted(all_candidates, key=attrgetter('area'), reverse=True)

            num_modified = 0
            num_deleted = 0
            num_created = 0

            for candidate in all_candidates:
                new_area = None
                for tmpid in level_areas.get(candidate.level, set()):
                    area = areas[tmpid]
                    if area.geometry.almost_equals(candidate.geometry, 1):
                        new_area = area
                        break

                if new_area is None:
                    potential_areas = [(tmpid, areas[tmpid].geometry.intersection(candidate.geometry.buffer(0)).area)
                                       for tmpid in level_areas.get(candidate.level, set())]
                    potential_areas = [(tmpid, size) for tmpid, size in potential_areas
                                       if candidate.area and size/candidate.area > 0.9]
                    if potential_areas:
                        num_modified += 1
                        new_area = areas[max(potential_areas, key=itemgetter(1))[0]]

                if new_area is None:
                    candidate.delete()
                    num_deleted += 1
                    continue

                candidate.geometry = new_area.geometry
                candidate.altitude = new_area.altitude
                candidate.save()
                areas_to_save.discard(new_area.tmpid)
                level_areas[new_area.level].discard(new_area.tmpid)

            for tmpid in areas_to_save:
                num_created += 1
                areas[tmpid].save()

            print(_('%d altitude areas built.') % len(areas))
            print(_('%d modified, %d deleted, %d created.') % (num_modified, num_deleted, num_created))
