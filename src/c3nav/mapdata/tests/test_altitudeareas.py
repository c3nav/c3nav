from decimal import Decimal
from typing import NamedTuple, Self

from django.test.testcases import TransactionTestCase
from shapely import normalize, Polygon, LineString, Point
from shapely.geometry.base import BaseGeometry

from c3nav.mapdata.models import AltitudeArea, Level, Space, Stair, AltitudeMarker, GroundAltitude
from c3nav.mapdata.models.geometry.level import AltitudeAreaPoint
from c3nav.mapdata.utils.geometry import unwrap_geom


class ExpectedAltitudeArea(NamedTuple):
    level: Level
    geometry: BaseGeometry
    altitude: Decimal | None = None
    points: frozenset[AltitudeAreaPoint] | None = None

    @classmethod
    def from_altitudearea(cls, altitudearea: AltitudeArea) -> Self:
        return cls(
            level=altitudearea.level,
            geometry=unwrap_geom(altitudearea.geometry),
            altitude=altitudearea.altitude,
            points=None if altitudearea.points is None else frozenset(altitudearea.points),
        )


class PolygonCuttingTests(TransactionTestCase):
    altitude = Decimal("13.70")

    def _assertAltitudeAreas(self, expected: set[ExpectedAltitudeArea]) -> tuple[int, ...]:
        actual = {ExpectedAltitudeArea.from_altitudearea(area): area.pk for area in AltitudeArea.objects.all()}
        self.assertSetEqual(set(actual), expected)
        return tuple(actual.values())  # noqa

    def test_no_data(self):
        AltitudeArea.recalculate()
        self.assertFalse(AltitudeArea.objects.exists())

    def _create_level(self, altitude: Decimal = None) -> Level:
        if altitude is None:
            altitude = self.altitude
        return Level.objects.create(
            base_altitude=altitude,
            short_label="0l",
            level_index="0i",
        )

    def _create_space(self, level) -> Space:
        return Space.objects.create(
            level=level,
            geometry=Polygon([(0, 0), (100, 0), (100, 100), (0, 100)]),
        )

    def test_level_no_spaces(self):
        self._create_level()
        AltitudeArea.recalculate()
        self._assertAltitudeAreas(set())

    def test_one_space_no_marker(self):
        level = self._create_level()
        space = self._create_space(level)
        AltitudeArea.recalculate()
        self._assertAltitudeAreas({
            ExpectedAltitudeArea(level=level, geometry=normalize(space.geometry), altitude=self.altitude)
        })

    def test_one_space_one_cut_space_no_marker(self):
        level = self._create_level()
        space = self._create_space(level)
        Stair.objects.create(space=space, geometry=LineString([(50, -1), (50, 101)]))
        AltitudeArea.recalculate()
        self._assertAltitudeAreas({
            ExpectedAltitudeArea(level=level, geometry=normalize(space.geometry), altitude=self.altitude)
        })

    def test_one_space_three_cuts_interpolate(self):
        level = self._create_level()
        space = self._create_space(level)
        Stair.objects.create(space=space, geometry=LineString([(30, -1), (30, 101)]))
        Stair.objects.create(space=space, geometry=LineString([(50, -1), (50, 101)]))
        Stair.objects.create(space=space, geometry=LineString([(70, -1), (70, 101)]))
        AltitudeMarker.objects.create(space=space, geometry=Point(20, 50),
                                      groundaltitude=GroundAltitude.objects.create(name="1", altitude=Decimal("1.00")))
        AltitudeMarker.objects.create(space=space, geometry=Point(80, 50),
                                      groundaltitude=GroundAltitude.objects.create(name="2", altitude=Decimal("2.00")))
        AltitudeArea.recalculate()

        self._assertAltitudeAreas({
            ExpectedAltitudeArea(level=level, altitude=Decimal("1.00"),
                                 geometry=normalize(Polygon([(0, 0), (30, 0), (30, 100), (0, 100)]))),
            ExpectedAltitudeArea(level=level, altitude=Decimal("1.33"),
                                 geometry=normalize(Polygon([(30, 0), (50, 0), (50, 100), (30, 100)]))),
            ExpectedAltitudeArea(level=level, altitude=Decimal("1.67"),
                                 geometry=normalize(Polygon([(50, 0), (70, 0), (70, 100), (50, 100)]))),
            ExpectedAltitudeArea(level=level, altitude=Decimal("2.00"),
                                 geometry=normalize(Polygon([(70, 0), (100, 0), (100, 100), (70, 100)]))),
        })

    def test_one_space_cross_cuts_interpolate(self):
        level = self._create_level()
        space = self._create_space(level)
        Stair.objects.create(space=space, geometry=LineString([(50, -1), (50, 101)]))
        Stair.objects.create(space=space, geometry=LineString([(-1, 50), (101, 50)]))
        Stair.objects.create(space=space, geometry=LineString([(-1, 101), (51, 49)]))
        AltitudeMarker.objects.create(space=space, geometry=Point(10, 10),
                                      groundaltitude=GroundAltitude.objects.create(name="1", altitude=Decimal("1.00")))
        AltitudeMarker.objects.create(space=space, geometry=Point(90, 90),
                                      groundaltitude=GroundAltitude.objects.create(name="2", altitude=Decimal("2.00")))
        AltitudeArea.recalculate()

        self._assertAltitudeAreas({
            ExpectedAltitudeArea(level=level, altitude=Decimal("1.00"),
                                 geometry=normalize(Polygon([(0, 0), (50, 0), (50, 50), (0, 50)]))),
            ExpectedAltitudeArea(level=level, altitude=Decimal("1.50"),
                                 geometry=normalize(Polygon([(50, 0), (100, 0), (100, 50), (50, 50)]))),
            ExpectedAltitudeArea(level=level, altitude=Decimal("1.33"),
                                 geometry=normalize(Polygon([(0, 50), (50, 50), (0, 100)]))),
            ExpectedAltitudeArea(level=level, altitude=Decimal("1.67"),
                                 geometry=normalize(Polygon([(50, 100), (50, 50), (0, 100)]))),
            ExpectedAltitudeArea(level=level, altitude=Decimal("2.00"),
                                 geometry=normalize(Polygon([(50, 50), (100, 50), (100, 100), (50, 100)]))),
        })