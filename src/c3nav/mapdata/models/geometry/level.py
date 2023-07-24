import logging
from collections import deque
from decimal import Decimal
from itertools import chain, combinations
from operator import attrgetter, itemgetter

import numpy as np
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils.functional import cached_property
from django.utils.text import format_lazy
from django.utils.translation import gettext_lazy as _
from scipy.sparse.csgraph._shortest_path import dijkstra
from shapely import prepared
from shapely.affinity import scale
from shapely.geometry import JOIN_STYLE, LineString, MultiPolygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from c3nav.mapdata.fields import GeometryField, I18nField
from c3nav.mapdata.grid import grid
from c3nav.mapdata.models import Level
from c3nav.mapdata.models.access import AccessRestrictionMixin
from c3nav.mapdata.models.geometry.base import GeometryMixin
from c3nav.mapdata.models.locations import SpecificLocation
from c3nav.mapdata.utils.cache.changes import changed_geometries
from c3nav.mapdata.utils.geometry import (assert_multilinestring, assert_multipolygon, clean_cut_polygon,
                                          cut_polygon_with_line)


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

    def details_display(self, **kwargs):
        result = super().details_display(**kwargs)
        result['display'].insert(3, (
            _('Level'),
            {
                'id': self.level_id,
                'slug': self.level.get_slug(),
                'title': self.level.title,
                'can_search': self.level.can_search,
            },
        ))
        result['level'] = self.level_id
        return result

    @property
    def subtitle(self):
        base_subtitle = super().subtitle
        level = getattr(self, '_level_cache', None)
        if level is not None:
            return format_lazy(_('{category}, {level}'),
                               category=base_subtitle,
                               level=level.title)
        return base_subtitle

    def register_change(self, force=False):
        force = force or self.all_geometry_changed
        if force or self.geometry_changed:
            changed_geometries.register(self.level_id, self.geometry if force else self.get_changed_geometry())

    def register_delete(self):
        changed_geometries.register(self.level_id, self.geometry)

    @classmethod
    def q_for_request(cls, request, prefix='', allow_none=False):
        return (
            super().q_for_request(request, prefix=prefix, allow_none=allow_none) &
            Level.q_for_request(request, prefix=prefix+'level__', allow_none=allow_none)
        )

    def save(self, *args, **kwargs):
        self.register_change()
        super().save(*args, **kwargs)


class Building(LevelGeometryMixin, models.Model):
    """
    The outline of a building on a specific level
    """
    geometry = GeometryField('polygon')

    class Meta:
        verbose_name = _('Building')
        verbose_name_plural = _('Buildings')
        default_related_name = 'buildings'


class Space(LevelGeometryMixin, SpecificLocation, models.Model):
    """
    An accessible space. Shouldn't overlap with spaces on the same level.
    """
    geometry = GeometryField('polygon')
    height = models.DecimalField(_('height'), max_digits=6, decimal_places=2, null=True, blank=True,
                                 validators=[MinValueValidator(Decimal('0'))])
    outside = models.BooleanField(default=False, verbose_name=_('only outside of building'))
    enter_description = I18nField(_('Enter description'), blank=True, fallback_language=None)
    base_mapdata_accessible = models.BooleanField(default=False,
                                                  verbose_name=_('always accessible (overwrites base mapdata setting)'))

    class Meta:
        verbose_name = _('Space')
        verbose_name_plural = _('Spaces')
        default_related_name = 'spaces'

    def _serialize(self, geometry=True, **kwargs):
        result = super()._serialize(geometry=geometry, **kwargs)
        result['outside'] = self.outside
        result['height'] = None if self.height is None else float(str(self.height))
        return result

    @property
    def grid_square(self):
        return grid.get_squares_for_bounds(self.geometry.bounds) or ''

    def details_display(self, editor_url=True, **kwargs):
        result = super().details_display(**kwargs)
        result['display'].extend([
            (_('height'), self.height),
            (_('outside only'), _('Yes') if self.outside else _('No')),
        ])
        if editor_url:
            result['editor_url'] = reverse('editor.spaces.detail', kwargs={'level': self.level_id, 'pk': self.pk})
        return result


class Door(LevelGeometryMixin, AccessRestrictionMixin, models.Model):
    """
    A connection between two spaces
    """
    geometry = GeometryField('polygon')

    class Meta:
        verbose_name = _('Door')
        verbose_name_plural = _('Doors')
        default_related_name = 'doors'


class ItemWithValue:
    def __init__(self, obj, func):
        self.obj = obj
        self._func = func

    @cached_property
    def value(self):
        return self._func()


class AltitudeArea(LevelGeometryMixin, models.Model):
    """
    An altitude area
    """
    geometry = GeometryField('multipolygon')
    altitude = models.DecimalField(_('altitude'), null=False, max_digits=6, decimal_places=2)
    altitude2 = models.DecimalField(_('second altitude'), null=True, max_digits=6, decimal_places=2)
    point1 = GeometryField('point', null=True)
    point2 = GeometryField('point', null=True)

    class Meta:
        verbose_name = _('Altitude Area')
        verbose_name_plural = _('Altitude Areas')
        default_related_name = 'altitudeareas'
        ordering = ('altitude', )

    def get_altitudes(self, points):
        points = np.asanyarray(points).reshape((-1, 2))
        if self.altitude2 is None:
            return np.full((points.shape[0], ), fill_value=float(self.altitude))

        slope = np.array(self.point2.coords) - np.array(self.point1.coords)
        distances = (np.sum(((points - np.array(self.point1.coords)) * slope), axis=1) / (slope ** 2).sum()).clip(0, 1)

        if self.altitude2 < self.altitude:
            min_altitude = float(self.altitude2)
            max_altitude = float(self.altitude)
        else:
            min_altitude = float(self.altitude)
            max_altitude = float(self.altitude2)

        return np.clip(
            float(self.altitude) + distances*(float(self.altitude2)-float(self.altitude)),
            a_min=min_altitude, a_max=max_altitude
        )

    @classmethod
    def recalculate(cls):
        # collect location areas
        all_areas = []
        all_ramps = []
        space_areas = {}
        spaces = {}
        levels = Level.objects.prefetch_related('buildings', 'doors', 'spaces', 'spaces__columns',
                                                'spaces__obstacles', 'spaces__lineobstacles', 'spaces__holes',
                                                'spaces__stairs', 'spaces__ramps', 'spaces__altitudemarkers')
        logger = logging.getLogger('c3nav')

        for level in levels:
            areas = []
            ramps = []
            stairs = []

            # collect all accessible areas on this level
            buildings_geom = unary_union(tuple(building.geometry.wrapped_geom for building in level.buildings.all()))
            for space in level.spaces.all():
                spaces[space.pk] = space
                space.orig_geometry = space.geometry
                if space.outside:
                    space.geometry = space.geometry.difference(buildings_geom)
                space_accessible = space.geometry.difference(
                    unary_union(tuple(c.geometry for c in space.columns.all() if c.access_restriction_id is None) +
                                tuple(o.geometry for o in space.obstacles.all() if o.altitude == 0) +
                                tuple(o.buffered_geometry for o in space.lineobstacles.all() if o.altitude == 0) +
                                tuple(h.geometry for h in space.holes.all()))
                )

                space_ramps = unary_union(tuple(r.geometry for r in space.ramps.all()))
                areas.append(space_accessible.difference(space_ramps))
                for geometry in assert_multipolygon(space_accessible.intersection(space_ramps)):
                    ramp = AltitudeArea(geometry=geometry, level=level)
                    ramp.geometry_prep = prepared.prep(geometry)
                    ramp.space = space.pk
                    ramps.append(ramp)

            areas = tuple(orient(polygon) for polygon in assert_multipolygon(
                unary_union(areas+list(door.geometry for door in level.doors.all()))
            ))

            # collect all stairs on this level
            for space in level.spaces.all():
                space_buffer = space.geometry.buffer(0.001, join_style=JOIN_STYLE.mitre)
                for stair in space.stairs.all():
                    stairs.extend(assert_multilinestring(
                        stair.geometry.intersection(space_buffer)
                    ))

            # divide areas using stairs
            for stair in stairs:
                areas = cut_polygon_with_line(areas, stair)

            # create altitudearea objects
            areas = [AltitudeArea(geometry=clean_cut_polygon(area), level=level)
                     for area in areas]

            # prepare area geometries
            for area in areas:
                area.geometry_prep = prepared.prep(area.geometry)

            # assign spaces to areas
            space_areas.update({space.pk: [] for space in level.spaces.all()})
            for area in areas:
                area.spaces = set()
                area.geometry_prep = prepared.prep(area.geometry)
                for space in level.spaces.all():
                    if area.geometry_prep.intersects(space.geometry):
                        area.spaces.add(space.pk)
                        space_areas[space.pk].append(area)

            # give altitudes to areas
            for space in level.spaces.all():
                for altitudemarker in space.altitudemarkers.all():
                    for area in space_areas[space.pk]:
                        if area.geometry_prep.contains(altitudemarker.geometry):
                            area.altitude = altitudemarker.altitude
                            break
                    else:
                        logger.error(
                            _('AltitudeMarker #%(marker_id)d in Space #%(space_id)d on Level %(level_label)s '
                              'is not placed in an accessible area') % {'marker_id': altitudemarker.pk,
                                                                        'space_id': space.pk,
                                                                        'level_label': level.short_label})

            # determine altitude area connections
            for area in areas:
                area.connected_to = []
            for area, other_area in combinations(areas, 2):
                if area.geometry_prep.intersects(other_area.geometry):
                    area.connected_to.append(other_area)
                    other_area.connected_to.append(area)

            # determine ramp connections
            for ramp in ramps:
                ramp.connected_to = []
                buffered = ramp.geometry.buffer(0.001)
                for area in areas:
                    if area.geometry_prep.intersects(buffered):
                        intersection = area.geometry.intersection(buffered)
                        ramp.connected_to.append((area, intersection))
                if len(ramp.connected_to) != 2:
                    if len(ramp.connected_to) == 0:
                        logger.warning('A ramp in space #%d has no connections!' % ramp.space)
                    elif len(ramp.connected_to) == 1:
                        logger.warning('A ramp in space #%d has only one connection!' % ramp.space)
                    else:
                        logger.warning('A ramp in space #%d has more than two connections!' % ramp.space)

            # add areas to global areas
            all_areas.extend(areas)
            all_ramps.extend(ramps)

        # give temporary ids to all areas
        areas = all_areas
        ramps = all_ramps
        for i, area in enumerate(areas):
            area.tmpid = i
        for area in areas:
            area.connected_to = set(area.tmpid for area in area.connected_to)
        for space in space_areas.keys():
            space_areas[space] = set(area.tmpid for area in space_areas[space])
        areas_without_altitude = set(area.tmpid for area in areas if area.altitude is None)

        # interpolate altitudes
        logger.info('Interpolating altitudes...')

        areas_with_altitude = [i for i in range(len(areas)) if i not in areas_without_altitude]
        for i, tmpid in enumerate(areas_with_altitude):
            areas[tmpid].i = i

        csgraph = np.zeros((len(areas), len(areas)), dtype=bool)
        for area in areas:
            for connected_tmpid in area.connected_to:
                csgraph[area.tmpid, connected_tmpid] = True

        repeat = True

        while repeat:
            repeat = False
            # noinspection PyTupleAssignmentBalance
            distances, predecessors = dijkstra(csgraph, directed=False, return_predecessors=True, unweighted=True)
            np_areas_with_altitude = np.array(areas_with_altitude, dtype=np.uint32)
            relevant_distances = distances[np_areas_with_altitude[:, None], np_areas_with_altitude]
            # noinspection PyTypeChecker
            for from_i, to_i in np.argwhere(np.logical_and(relevant_distances < np.inf, relevant_distances > 1)):
                from_area = areas[areas_with_altitude[from_i]]
                to_area = areas[areas_with_altitude[to_i]]
                if from_area.altitude == to_area.altitude:
                    continue

                path = [to_area.tmpid]
                while path[-1] != from_area.tmpid:
                    path.append(predecessors[from_area.tmpid, path[-1]])

                from_altitude = from_area.altitude
                delta_altitude = (to_area.altitude-from_altitude)/(len(path)-1)

                if set(path[1:-1]).difference(areas_without_altitude):
                    continue

                for i, tmpid in enumerate(reversed(path[1:-1]), start=1):
                    area = areas[tmpid]
                    area.altitude = Decimal(from_altitude+delta_altitude*i).quantize(Decimal('1.00'))
                    areas_without_altitude.discard(tmpid)
                    area.i = len(areas_with_altitude)
                    areas_with_altitude.append(tmpid)

                for from_tmpid, to_tmpid in zip(path[:-1], path[1:]):
                    csgraph[from_tmpid, to_tmpid] = False
                    csgraph[to_tmpid, from_tmpid] = False

                repeat = True

        # remaining areas: copy altitude from connected areas if any
        repeat = True
        while repeat:
            repeat = False
            for tmpid in tuple(areas_without_altitude):
                area = areas[tmpid]
                connected_with_altitude = area.connected_to-areas_without_altitude
                if connected_with_altitude:
                    area.altitude = areas[next(iter(connected_with_altitude))].altitude
                    areas_without_altitude.discard(tmpid)
                    repeat = True

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
                    altitude_areas[altitude] = unary_union(altitude_areas[altitude])
                for tmpid in contained_areas_without_altitude:
                    area = areas[tmpid]
                    area.altitude = min(altitude_areas.items(), key=lambda aa: aa[1].distance(area.geometry))[0]
                areas_without_altitude.difference_update(contained_areas_without_altitude)

        # last fallback: level base_altitude
        for tmpid in areas_without_altitude:
            area = areas[tmpid]
            area.altitude = area.level.base_altitude

        # prepare per-level operations
        level_areas = {}
        for area in areas:
            level_areas.setdefault(area.level, set()).add(area.tmpid)

        # make sure there is only one altitude area per altitude per level
        for level in levels:
            areas_by_altitude = {}
            for tmpid in level_areas.get(level, []):
                area = areas[tmpid]
                areas_by_altitude.setdefault(area.altitude, []).append(area.geometry)

            level_areas[level] = [AltitudeArea(level=level, geometry=unary_union(geometries), altitude=altitude)
                                  for altitude, geometries in areas_by_altitude.items()]

        # renumber joined areas
        areas = list(chain(*(a for a in level_areas.values())))
        for i, area in enumerate(areas):
            area.tmpid = i

        # finalize ramps
        for ramp in ramps:
            if not ramp.connected_to:
                for area in space_areas[ramp.space]:
                    ramp.altitude = areas[area].altitude
                    break
                else:
                    ramp.altitude = ramp.level.base_altitude
                continue

            if len(ramp.connected_to) == 1:
                ramp.altitude = ramp.connected_to[0][0].altitude
                continue

            if len(ramp.connected_to) > 2:
                ramp.connected_to = sorted(ramp.connected_to, key=lambda item: item[1].area)[-2:]

            ramp.point1 = ramp.connected_to[0][1].centroid
            ramp.point2 = ramp.connected_to[1][1].centroid
            ramp.altitude = ramp.connected_to[0][0].altitude
            ramp.altitude2 = ramp.connected_to[1][0].altitude

            ramp.tmpid = len(areas)
            areas.append(ramp)
            level_areas[ramp.level].append(ramp)

        #
        # we have altitude areas, but they only cover accessible space for now
        # however, we need obstacles to be part of altitude areas too.
        # this is where we do that.
        #
        for level in levels:
            logger.info('Assign remaining space (%s)...' % level.title)
            for space in level.spaces.all():
                space.geometry = space.orig_geometry

            buildings_geom = unary_union(tuple(b.geometry.wrapped_geom for b in level.buildings.all()))
            doors_geom = unary_union(tuple(d.geometry for d in level.doors.all()))
            space_geom = unary_union(tuple((s.geometry if not s.outside else s.geometry.difference(buildings_geom))
                                           for s in level.spaces.all()))

            # accessible area on this level is doors + spaces - holes
            accessible_area = unary_union((doors_geom, space_geom))
            for space in level.spaces.all():
                accessible_area = accessible_area.difference(space.geometry.intersection(
                    unary_union(tuple(h.geometry for h in space.holes.all()))
                ))

            # areas mean altitude areas (including ramps) here
            our_areas = level_areas.get(level, [])
            for area in our_areas:
                area.orig_geometry = area.geometry
                area.orig_geometry_prep = prepared.prep(area.geometry)
                area.polygons_to_add = deque()

            stairs = []
            for space in level.spaces.all():
                space_geom = space.geometry
                if space.outside:
                    space_geom = space_geom.difference(buildings_geom)
                space_geom_prep = prepared.prep(space_geom)
                holes_geom = unary_union(tuple(h.geometry for h in space.holes.all()))

                # remaining_space means remaining space (=obstacles) that still needs to be added to altitude areas
                remaining_space = (
                    tuple(o.geometry for o in space.obstacles.all()) +
                    tuple(o.buffered_geometry for o in space.lineobstacles.all())
                )
                # make sure to remove everything outside the space the obstacles are in as well as holes
                remaining_space = tuple(g.intersection(space_geom).difference(holes_geom)
                                        for g in remaining_space
                                        if space_geom_prep.intersects(g))
                # we need this to be a list of simple normal polygons
                remaining_space = tuple(chain(*(
                    assert_multipolygon(g) for g in remaining_space if not g.is_empty
                )))
                if not remaining_space:
                    # if there are no remaining spaces? great, we're done here.
                    continue

                cuts = []
                for cut in chain(*(assert_multilinestring(stair.geometry) for stair in space.stairs.all()),
                                 (ramp.geometry.exterior for ramp in space.ramps.all())):
                    for coord1, coord2 in zip(tuple(cut.coords)[:-1], tuple(cut.coords)[1:]):
                        line = space_geom.intersection(LineString([coord1, coord2]))
                        if line.is_empty:
                            continue
                        factor = (line.length + 2) / line.length
                        line = scale(line, xfact=factor, yfact=factor)
                        centroid = line.centroid
                        line = min(assert_multilinestring(space_geom.intersection(line)),
                                   key=lambda line_: line_.centroid.distance(centroid), default=None)
                        cuts.append(scale(line, xfact=1.01, yfact=1.01))

                remaining_space = tuple(
                    orient(polygon) for polygon in remaining_space
                )

                for cut in cuts:
                    remaining_space = tuple(chain(*(cut_polygon_with_line(geom, cut)
                                                    for geom in remaining_space)))
                remaining_space = MultiPolygon(remaining_space)

                for polygon in assert_multipolygon(remaining_space):
                    polygon = clean_cut_polygon(polygon).buffer(0)
                    buffered = polygon.buffer(0.001)

                    center = polygon.centroid
                    touches = tuple(ItemWithValue(area, lambda: buffered.intersection(area.orig_geometry).area)
                                    for area in our_areas
                                    if area.orig_geometry_prep.intersects(buffered))
                    if len(touches) == 1:
                        area = touches[0].obj
                    elif touches:
                        min_touches = sum((t.value for t in touches), 0)/4
                        area = max(touches, key=lambda item: (item.value > min_touches,
                                                              item.obj.altitude2 is not None,
                                                              item.obj.altitude,
                                                              item.value)).obj
                    else:
                        area = min(our_areas,
                                   key=lambda a: a.orig_geometry.distance(center)-(0 if a.altitude2 is None else 0.6))
                    area.polygons_to_add.append(polygon)

            for i_area, area in enumerate(our_areas):
                if area.polygons_to_add:
                    area.geometry = unary_union((area.geometry.buffer(0), *area.polygons_to_add))
                del area.polygons_to_add

        for level in levels:
            level_areas[level] = set(area.tmpid for area in level_areas.get(level, []))

        # save to database
        areas_to_save = set(range(len(areas)))

        all_candidates = AltitudeArea.objects.select_related('level')
        for candidate in all_candidates:
            candidate.area = candidate.geometry.area
            candidate.geometry_prep = prepared.prep(candidate.geometry)
        all_candidates = sorted(all_candidates, key=attrgetter('area'), reverse=True)

        num_modified = 0
        num_deleted = 0
        num_created = 0

        field = AltitudeArea._meta.get_field('geometry')

        for candidate in all_candidates:
            new_area = None

            if candidate.altitude2 is None:
                for tmpid in level_areas.get(candidate.level, set()):
                    area = areas[tmpid]
                    if area.altitude2 is None and area.altitude == candidate.altitude:
                        new_area = area
                        break
            else:
                potential_areas = [areas[tmpid] for tmpid in level_areas.get(candidate.level, set())]
                potential_areas = [area for area in potential_areas
                                   if (candidate.altitude, candidate.altitude2) in ((area.altitude, area.altitude2),
                                                                                    (area.altitude2, area.altitude))]
                potential_areas = [(area, area.geometry.intersection(candidate.geometry).area)
                                   for area in potential_areas
                                   if candidate.geometry_prep.intersects(area.geometry)]
                if potential_areas:
                    new_area = max(potential_areas, key=itemgetter(1))[0]

            if new_area is None:
                candidate.delete()
                num_deleted += 1
                continue

            if not field.get_final_value(new_area.geometry).equals_exact(candidate.geometry, 0.00001):
                num_modified += 1

            candidate.geometry = new_area.geometry
            candidate.altitude = new_area.altitude
            candidate.altitude2 = new_area.altitude2
            candidate.point1 = new_area.point1
            candidate.point2 = new_area.point2
            candidate.save()
            areas_to_save.discard(new_area.tmpid)
            level_areas[new_area.level].discard(new_area.tmpid)

        for tmpid in areas_to_save:
            num_created += 1
            areas[tmpid].save()

        logger = logging.getLogger('c3nav')
        logger.info(_('%d altitude areas built.') % len(areas))
        logger.info(_('%(num_modified)d modified, %(num_deleted)d deleted, %(num_created)d created.') %
                    {'num_modified': num_modified, 'num_deleted': num_deleted, 'num_created': num_created})
