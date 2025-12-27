from typing import Optional

from shapely import Point, distance
from shapely.ops import unary_union, nearest_points

from c3nav.mapdata.models import Level, Space
from c3nav.mapdata.utils.geometry import unwrap_geom
from c3nav.routing.router import RouterRestrictionSet


class PointPlacementHelper:
    def __init__(self):
        self.spaces_for_level = {}
        self.levels = tuple(Level.objects.values_list("pk", flat=True))
        self.lower_levels_for_level = {pk: self.levels[:i] for i, pk in enumerate(self.levels)}

        for space in Space.objects.select_related('level').prefetch_related('holes'):
            self.spaces_for_level.setdefault(space.level_id, []).append(space)

    def get_point_and_space(self, level_id: int, point: Point, name: Optional[str] = None,
                            restrictions: Optional[RouterRestrictionSet] = None, max_space_distance=1.5):
        # determine space
        restricted_spaces = restrictions.spaces if restrictions else ()
        possible_spaces = [space for space in self.spaces_for_level[level_id]
                           if space.pk not in restricted_spaces and space.geometry.intersects(point)]

        if not possible_spaces:
            possible_spaces = [space for space in self.spaces_for_level[level_id]
                               if (space.pk not in restricted_spaces
                                   and distance(unwrap_geom(space.geometry), point) < max_space_distance)]
            if len(possible_spaces) == 1:
                new_space = possible_spaces[0]
                the_distance = distance(unwrap_geom(new_space.geometry), point)
                if name:
                    print(f"SUCCESS: {name} is {the_distance:.02f}m away from {new_space.title}")
            elif len(possible_spaces) > 1:
                new_space = min(possible_spaces, key=lambda s: distance(unwrap_geom(s.geometry), point))
                if name:
                    print(f"WARNING: {name} could be in multiple spaces ({possible_spaces}, picking {new_space}, "
                          f"which is {distance(unwrap_geom(new_space.geometry), point)}m away...")
            else:
                if name:
                    print(f"ERROR: {name} is not within any space on level {level_id} ({point})")
                return None, None

            # move point into space if needed
            new_space_geometry = new_space.geometry.difference(
                unary_union([unwrap_geom(hole.geometry) for hole in new_space.columns.all()])
            )
            if new_space_geometry.is_empty:
                new_space_geometry = new_space.geometry
            if not new_space_geometry.intersects(point):
                point = nearest_points(new_space_geometry.buffer(-0.05), point)[0]
        elif len(possible_spaces) == 1:
            new_space = possible_spaces[0]
            if name:
                print(f"SUCCESS: {name} is in {new_space.title}")
        else:
            if name:
                print(f"WARNING: {name} could be in multiple spaces, picking one...")
            new_space = possible_spaces[0]

        lower_levels = self.lower_levels_for_level[new_space.level_id]
        for lower_level in reversed(lower_levels):
            # let's go through the lower levels
            if not unary_union([unwrap_geom(h.geometry) for h in new_space.holes.all()]).intersects(point):
                # current selected spacae is fine, that's it
                break
            if name:
                print(f"NOTE: {name} is in a hole, looking lower...")

            # find a lower space
            possible_spaces = [space for space in self.spaces_for_level[lower_level]
                               if space.pk not in restricted_spaces and space.geometry.intersects(point)]
            if possible_spaces:
                new_space = possible_spaces[0]
                if name:
                    print(f"NOTE: {name} moved to lower space {new_space}")
        else:
            if name:
                print(f"WARNING: {name} couldn't find a lower space, still in a hole")

        return new_space, point
