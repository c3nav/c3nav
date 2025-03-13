from django.conf import settings
from django.utils.text import format_lazy
from django.utils.translation import gettext_lazy as _
from shapely import Point

from c3nav.mapdata.models.geometry.level import Space


# todo: written fast, make better
class DistanceLocationFeature:
    location = None
    xyz = None

    @classmethod
    def add_distance_location_display(cls, result: dict, location):
        if not settings.DISTANCE_FROM_LOCATION:
            return

        try:
            from c3nav.routing.router import Router
            router = Router.load()
        except:
            return

        if cls.location is None:
            from c3nav.mapdata.models.locations import LocationSlug

            try:
                cls.location = LocationSlug.objects.get(
                    pk=settings.DISTANCE_FROM_LOCATION).get_child()
                point = cls.location.point
                if not isinstance(point, Point):
                    point = Point(point[1:])
            except:
                return

            cls.xyz = (
                *(point[1:] if isinstance(point, tuple) else (point.x, point.y)),
                router.spaces[
                    cls.location.pk if isinstance(cls.location, Space) else (
                        cls.location.space_id if hasattr(cls.location, "space_id") else cls.location.space.id
                    )
                ].altitudearea_for_point(point).get_altitude(point)
            )

        try:
            point = location.point
            if not isinstance(point, Point):
                point = Point(point[1:])
            other_xyz = (
                *(point[1:] if isinstance(point, tuple) else (point.x, point.y)),
                router.spaces[
                    location.pk if isinstance(location, Space) else (
                        location.space_id if hasattr(location, "space_id") else location.space.id
                    )
                ].altitudearea_for_point(point).get_altitude(point)
            )
        except:
            return

        import numpy as np
        distance = np.linalg.norm(tuple((x-y) for x, y in zip(cls.xyz, other_xyz)))

        result["display"].append(
            (format_lazy(_('Distance from {location}'), location=cls.location.title), '%.1f m' % distance)
        )
