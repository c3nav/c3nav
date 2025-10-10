from decimal import Decimal
from typing import NamedTuple, Self

from django.test.testcases import TransactionTestCase
from shapely import normalize, Polygon, LineString, Point, MultiPolygon, box
from shapely.geometry.base import BaseGeometry

from c3nav.mapdata.models import AltitudeArea, Level, Space, Stair, AltitudeMarker, GroundAltitude, Obstacle, \
    LineObstacle, AccessRestriction
from c3nav.mapdata.models.geometry.level import AltitudeAreaPoint, Building
from c3nav.mapdata.models.geometry.space import Column, Hole, Ramp
from c3nav.mapdata.utils.geometry import unwrap_geom


class ExpectedAltitudeArea(NamedTuple):
    level: int
    geometry: str
    altitude: Decimal | None = None
    points: frozenset[AltitudeAreaPoint] | None = None

    @classmethod
    def new(cls, level: Level, geometry: BaseGeometry, altitude: Decimal | None = None,
            points: frozenset[AltitudeAreaPoint] | None = None) -> Self:
        return cls(
            level=level.pk,
            geometry=normalize(geometry).wkt,
            altitude=altitude,
            points=points,
        )

    @classmethod
    def from_altitudearea(cls, altitudearea: AltitudeArea) -> Self:
        return cls(
            level=altitudearea.level.pk,
            geometry=unwrap_geom(altitudearea.geometry).wkt,
            altitude=altitudearea.altitude,
            points=None if altitudearea.points is None else frozenset(altitudearea.points),
        )


class PolygonCuttingTests(TransactionTestCase):
    altitude = Decimal("13.70")

    def setUp(self):
        self.restriction_1 = AccessRestriction.objects.create(titles={"en": "Restriction 1"})

    def _assertAltitudeAreas(self, expected: set[ExpectedAltitudeArea]) -> tuple[int, ...]:
        actual = {ExpectedAltitudeArea.from_altitudearea(area): area.pk    # pragma: no branch
                  for area in AltitudeArea.objects.all()}
        self.assertSetEqual(set(actual), expected)
        return tuple(actual.values())  # noqa

    def test_no_data(self):
        AltitudeArea.recalculate()
        self.assertFalse(AltitudeArea.objects.exists())

    def _create_level(self, altitude: Decimal = None) -> Level:
        if altitude is None:  # pragma: no branch
            altitude = self.altitude
        return Level.objects.create(
            base_altitude=altitude,
            short_label="0l",
            level_index="0i",
        )

    def _create_space(self, level, offset=0, outside=False) -> Space:
        return Space.objects.create(
            level=level,
            geometry=box(0+offset, 0, 100+offset, 100),
            outside=outside,
        )

    def test_level_no_spaces(self):
        self._create_level()
        AltitudeArea.recalculate()
        self._assertAltitudeAreas(set())

    def test_one_space_filled_with_hole(self):
        level = self._create_level()
        space = self._create_space(level)
        Hole.objects.create(space=space, geometry=box(-10, -10, 110, 110))
        AltitudeArea.recalculate()
        self._assertAltitudeAreas(set())

    def test_one_space_no_marker(self):
        level = self._create_level()
        space = self._create_space(level)
        AltitudeArea.recalculate()
        self._assertAltitudeAreas({
            ExpectedAltitudeArea.new(level=level, geometry=space.geometry, altitude=self.altitude)
        })

    def test_one_space_one_cut_space_no_marker(self):
        level = self._create_level()
        space = self._create_space(level)
        Stair.objects.create(space=space, geometry=LineString([(50, -1), (50, 101)]))
        AltitudeArea.recalculate()
        self._assertAltitudeAreas({
            ExpectedAltitudeArea.new(level=level, geometry=space.geometry, altitude=self.altitude)
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
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("1.00"), geometry=box(0, 0, 30, 100)),
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("1.33"), geometry=box(30, 0, 50, 100)),
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("1.67"), geometry=box(50, 0, 70, 100)),
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("2.00"), geometry=box(70, 0, 100, 100)),
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
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("1.00"), geometry=box(0, 0, 50, 50)),
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("1.50"), geometry=box(50, 0, 100, 50)),
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("1.33"),
                                     geometry=Polygon([(0, 50), (50, 50), (0, 100)])),
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("1.67"),
                                     geometry=Polygon([(50, 100), (50, 50), (0, 100)])),
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("2.00"), geometry=box(50, 50, 100, 100)),
        })

    def test_altitudemarker_outside_area(self):
        level = self._create_level()
        space = self._create_space(level)
        Stair.objects.create(space=space, geometry=LineString([(50, -1), (50, 101)]))
        AltitudeMarker.objects.create(space=space, geometry=Point(20, 50),
                                      groundaltitude=GroundAltitude.objects.create(name="1", altitude=Decimal("1.00")))
        AltitudeMarker.objects.create(space=space, geometry=Point(110, 50),
                                      groundaltitude=GroundAltitude.objects.create(name="2", altitude=Decimal("2.00")))
        AltitudeArea.recalculate()

        self._assertAltitudeAreas({
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("1.00"), geometry=box(0, 0, 100, 100)),
        })

    def test_altitudemarker_in_obstacle(self):
        level = self._create_level()
        space = self._create_space(level)
        Stair.objects.create(space=space, geometry=LineString([(40, -1), (40, 101)]))
        Stair.objects.create(space=space, geometry=LineString([(60, -1), (60, 101)]))
        Obstacle.objects.create(space=space, geometry=Polygon([(90, 90), (101, 90), (101, 101), (90, 101)]))
        AltitudeMarker.objects.create(space=space, geometry=Point(20, 50),
                                      groundaltitude=GroundAltitude.objects.create(name="1", altitude=Decimal("1.00")))
        AltitudeMarker.objects.create(space=space, geometry=Point(95, 95),
                                      groundaltitude=GroundAltitude.objects.create(name="2", altitude=Decimal("2.00")))
        AltitudeArea.recalculate()
        self._assertAltitudeAreas({
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("1.00"), geometry=box(0, 0, 40, 100)),
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("1.50"), geometry=box(40, 0, 60, 100)),
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("2.00"), geometry=box(60, 0, 100, 100)),
        })

    def test_polygon_obstacle_is_a_cut(self):
        level = self._create_level()
        space = self._create_space(level)
        Stair.objects.create(space=space, geometry=LineString([(50, -1), (50, 50)]))
        Obstacle.objects.create(space=space, geometry=Polygon([(49, 49), (51, 49), (51, 101), (49, 101)]))
        AltitudeMarker.objects.create(space=space, geometry=Point(10, 10),
                                      groundaltitude=GroundAltitude.objects.create(name="1", altitude=Decimal("1.00")))
        AltitudeMarker.objects.create(space=space, geometry=Point(90, 90),
                                      groundaltitude=GroundAltitude.objects.create(name="2", altitude=Decimal("2.00")))
        AltitudeArea.recalculate()
        self._assertAltitudeAreas({
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("1.00"),
                                     geometry=Polygon([(0, 0), (50, 0), (50, 49), (49, 49), (49, 100), (0, 100)])),
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("2.00"),
                                     geometry=Polygon([(50, 0), (100, 0), (100, 100), (49, 100), (49, 49), (50, 49)])),
        })

    def test_line_obstacle_is_a_cut(self):
        level = self._create_level()
        space = self._create_space(level)
        Stair.objects.create(space=space, geometry=LineString([(50, -1), (50, 50)]))
        LineObstacle.objects.create(space=space, geometry=LineString([(50, 49), (50, 101)]), width=0.2)
        AltitudeMarker.objects.create(space=space, geometry=Point(10, 10),
                                      groundaltitude=GroundAltitude.objects.create(name="1", altitude=Decimal("1.00")))
        AltitudeMarker.objects.create(space=space, geometry=Point(90, 90),
                                      groundaltitude=GroundAltitude.objects.create(name="2", altitude=Decimal("2.00")))
        AltitudeArea.recalculate()
        self._assertAltitudeAreas({
            ExpectedAltitudeArea.new(
                level=level, altitude=Decimal("1.00"),
                geometry=Polygon([(0, 0), (50, 0), (50, 49), (49.9, 49), (49.9, 100), (0, 100)])
            ),
            ExpectedAltitudeArea.new(
                level=level, altitude=Decimal("2.00"),
                geometry=Polygon([(50, 0), (100, 0), (100, 100), (49.9, 100), (49.9, 49), (50, 49)])
            ),
        })

    def test_raised_obstacle_is_not_a_cut(self):
        level = self._create_level()
        space = self._create_space(level)
        Stair.objects.create(space=space, geometry=LineString([(50, -1), (50, 50)]))
        LineObstacle.objects.create(space=space, geometry=LineString([(50, 49), (50, 101)]), width=0.2, altitude=0.1)
        AltitudeMarker.objects.create(space=space, geometry=Point(10, 10),
                                      groundaltitude=GroundAltitude.objects.create(name="1", altitude=Decimal("1.00")))
        AltitudeMarker.objects.create(space=space, geometry=Point(90, 90),
                                      groundaltitude=GroundAltitude.objects.create(name="2", altitude=Decimal("2.00")))
        AltitudeArea.recalculate()
        self._assertAltitudeAreas({
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("2.00"), geometry=box(0, 0, 100, 100)),
        })

    def test_obstacle_gets_cut_too(self):
        level = self._create_level()
        space = self._create_space(level)
        Stair.objects.create(space=space, geometry=LineString([(50, -1), (50, 101)]))
        LineObstacle.objects.create(space=space, geometry=LineString([(50, 49), (50, 101)]), width=0.2)
        AltitudeMarker.objects.create(space=space, geometry=Point(10, 10),
                                      groundaltitude=GroundAltitude.objects.create(name="1", altitude=Decimal("1.00")))
        AltitudeMarker.objects.create(space=space, geometry=Point(90, 90),
                                      groundaltitude=GroundAltitude.objects.create(name="2", altitude=Decimal("2.00")))
        AltitudeArea.recalculate()
        self._assertAltitudeAreas({
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("1.00"), geometry=box(0, 0, 50, 100)),
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("2.00"), geometry=box(50, 0, 100, 100)),
        })

    def test_staircase_with_middle_divider_nearest_area(self):
        level = self._create_level()
        space = self._create_space(level)
        Stair.objects.create(space=space, geometry=LineString([(40, -1), (40, 101)]))
        Stair.objects.create(space=space, geometry=LineString([(60, -1), (60, 101)]))
        LineObstacle.objects.create(space=space, geometry=LineString([(-1, 50), (101, 50)]), width=0.2)
        AltitudeMarker.objects.create(space=space, geometry=Point(10, 10),
                                      groundaltitude=GroundAltitude.objects.create(name="1", altitude=Decimal("1.00")))
        AltitudeMarker.objects.create(space=space, geometry=Point(90, 10),
                                      groundaltitude=GroundAltitude.objects.create(name="2", altitude=Decimal("2.00")))
        AltitudeArea.recalculate()
        self._assertAltitudeAreas({
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("1.00"), geometry=box(0, 0, 40, 100)),
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("1.50"), geometry=box(40, 0, 60, 100)),
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("2.00"), geometry=box(60, 0, 100, 100)),
        })

    def test_staircase_with_marker_on_stair(self):
        level = self._create_level()
        space = self._create_space(level)
        Stair.objects.create(space=space, geometry=LineString([(40, -1), (40, 101)]))
        Stair.objects.create(space=space, geometry=LineString([(60, -1), (60, 101)]))
        AltitudeMarker.objects.create(space=space, geometry=Point(10, 10),
                                      groundaltitude=GroundAltitude.objects.create(name="1", altitude=Decimal("1.00")))
        AltitudeMarker.objects.create(space=space, geometry=Point(60, 10),
                                      groundaltitude=GroundAltitude.objects.create(name="2", altitude=Decimal("2.00")))
        AltitudeArea.recalculate()
        self._assertAltitudeAreas({
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("1.00"), geometry=box(0, 0, 100, 100)),
        })

    def test_staircase_with_marker_in_split_obstacle(self):
        level = self._create_level()
        space = self._create_space(level)
        Stair.objects.create(space=space, geometry=LineString([(50, -1), (50, 51)]))
        LineObstacle.objects.create(space=space, geometry=LineString([(50, 49), (50, 101)]), width=0.2)
        AltitudeMarker.objects.create(space=space, geometry=Point(50.05, 70),
                                      groundaltitude=GroundAltitude.objects.create(name="1", altitude=Decimal("1.00")))
        AltitudeArea.recalculate()
        self._assertAltitudeAreas({
            ExpectedAltitudeArea.new(level=level, altitude=self.altitude, geometry=box(0, 0, 100, 100)),
        })

    def test_t_shaped_staircase(self):
        level = self._create_level()
        space = Space.objects.create(
            level=level,
            geometry=box(-25, 0, 25, 10).union(box(-5, 0, 5, 30)),
        )
        Stair.objects.create(space=space, geometry=LineString([(-15, 0), (-15, 10)]))
        Stair.objects.create(space=space, geometry=LineString([(15, 0), (15, 10)]))
        Stair.objects.create(space=space, geometry=LineString([(-5, 0), (-5, 10), (5, 10), (5, 0)]))
        Stair.objects.create(space=space, geometry=LineString([(-10, 20), (10, 20)]))
        altitude1 = GroundAltitude.objects.create(name="1", altitude=Decimal("1.00"))
        altitude2 = GroundAltitude.objects.create(name="2", altitude=Decimal("2.00"))
        AltitudeMarker.objects.create(space=space, geometry=Point(-20, 5), groundaltitude=altitude1)
        AltitudeMarker.objects.create(space=space, geometry=Point(20, 5), groundaltitude=altitude1)
        AltitudeMarker.objects.create(space=space, geometry=Point(0, 25), groundaltitude=altitude2)
        AltitudeArea.recalculate()
        self._assertAltitudeAreas({
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("1.00"), geometry=MultiPolygon((
                box(-25, 0, -15, 10), box(15, 0, 25, 10)
            ))),
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("1.25"), geometry=MultiPolygon((
                box(-15, 0, -5, 10), box(5, 0, 15, 10)
            ))),
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("1.50"), geometry=box(-5, 0, 5, 10)),
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("1.75"), geometry=box(-5, 10, 5, 20)),
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("2.00"), geometry=box(-5, 20, 5, 30)),
        })

    def test_disconnected_space(self):
        level = self._create_level()
        space = self._create_space(level)
        space2 = self._create_space(level, offset=200)
        space3 = self._create_space(level, offset=400)
        AltitudeMarker.objects.create(space=space, geometry=Point(50, 70),
                                      groundaltitude=GroundAltitude.objects.create(name="1", altitude=Decimal("1.00")))
        AltitudeMarker.objects.create(space=space2, geometry=Point(250, 70),
                                      groundaltitude=GroundAltitude.objects.create(name="2", altitude=Decimal("2.00")))
        AltitudeArea.recalculate()
        self._assertAltitudeAreas({
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("1.00"), geometry=box(0, 0, 100, 100)),
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("2.00"), geometry=MultiPolygon((box(200, 0, 300, 100),
                                                                                                   box(400, 0, 500, 100)))),
        })

    def test_space_clipped_by_building(self):
        level = self._create_level()
        space = self._create_space(level, outside=True)
        Building.objects.create(
            level=level,
            geometry=Polygon([(-10, -10), (-10, 10), (10, 10), (10, -10)]),
        )
        AltitudeMarker.objects.create(space=space, geometry=Point(5, 5),
                                      groundaltitude=GroundAltitude.objects.create(name="1", altitude=Decimal("1.00")))
        AltitudeArea.recalculate()
        self._assertAltitudeAreas({
            ExpectedAltitudeArea.new(level=level, altitude=self.altitude,
                                     geometry=Polygon([(0, 10), (10, 10), (10, 0), (100, 0), (100, 100), (0, 100)])),
        })

    def test_space_clipped_by_column(self):
        level = self._create_level()
        Building.objects.create(
            level=level,
            geometry=Polygon([(-10, -10), (-10, 110), (110, 110), (110, -10)]),
        )
        space = self._create_space(level)
        Column.objects.create(
            space=space,
            geometry=Polygon([(40, 40), (40, 60), (60, 60), (60, 40)]),
        )
        space2 = Space.objects.create(
            level=level,
            geometry=Polygon([(45, 45), (45, 55), (55, 55), (55, 45)]),
        )
        AltitudeMarker.objects.create(space=space, geometry=Point(10, 10),
                                      groundaltitude=GroundAltitude.objects.create(name="1", altitude=Decimal("1.00")))
        AltitudeMarker.objects.create(space=space2, geometry=Point(50, 50),
                                      groundaltitude=GroundAltitude.objects.create(name="2", altitude=Decimal("2.00")))
        AltitudeArea.recalculate()
        self._assertAltitudeAreas({
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("1.00"),
                                     geometry=box(0, 0, 100, 100).difference(box(40, 40, 60, 60))),
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("2.00"), geometry=box(45, 45, 55, 55)),
        })

    def test_space_not_clipped_by_restricted_column(self):
        level = self._create_level()
        Building.objects.create(
            level=level,
            geometry=Polygon([(-10, -10), (-10, 110), (110, 110), (110, -10)]),
        )
        space = self._create_space(level)
        Column.objects.create(
            space=space,
            geometry=Polygon([(40, 40), (40, 60), (60, 60), (60, 40)]),
            access_restriction=self.restriction_1,
        )
        Space.objects.create(
            level=level,
            geometry=Polygon([(45, 45), (45, 55), (55, 55), (55, 45)]),
        )
        AltitudeMarker.objects.create(space=space, geometry=Point(10, 10),
                                      groundaltitude=GroundAltitude.objects.create(name="1", altitude=Decimal("1.00")))
        AltitudeMarker.objects.create(space=space, geometry=Point(50, 50),
                                      groundaltitude=GroundAltitude.objects.create(name="2", altitude=Decimal("2.00")))
        AltitudeArea.recalculate()
        self._assertAltitudeAreas({
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("2.00"), geometry=box(0, 0, 100, 100)),
        })

    def test_space_clipped_by_hole(self):
        level = self._create_level()
        Building.objects.create(
            level=level,
            geometry=Polygon([(-10, -10), (-10, 110), (110, 110), (110, -10)]),
        )
        space = self._create_space(level)
        Hole.objects.create(
            space=space,
            geometry=Polygon([(40, 40), (40, 60), (60, 60), (60, 40)]),
        )
        space2 = Space.objects.create(
            level=level,
            geometry=Polygon([(45, 45), (45, 55), (55, 55), (55, 45)]),
        )
        AltitudeMarker.objects.create(space=space, geometry=Point(10, 10),
                                      groundaltitude=GroundAltitude.objects.create(name="1", altitude=Decimal("1.00")))
        AltitudeMarker.objects.create(space=space2, geometry=Point(50, 50),
                                      groundaltitude=GroundAltitude.objects.create(name="2", altitude=Decimal("2.00")))
        AltitudeArea.recalculate()
        self._assertAltitudeAreas({
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("1.00"), geometry=box(0, 0, 100, 100).difference(box(40, 40, 60, 60))),
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("2.00"), geometry=box(45, 45, 55, 55)),
        })

    def test_spaces_overlap(self):
        level = self._create_level()
        space = self._create_space(level)
        space2 = self._create_space(level, offset=10)
        AltitudeMarker.objects.create(space=space, geometry=Point(10, 10),
                                      groundaltitude=GroundAltitude.objects.create(name="1", altitude=Decimal("1.00")))
        AltitudeMarker.objects.create(space=space2, geometry=Point(100, 10),
                                      groundaltitude=GroundAltitude.objects.create(name="2", altitude=Decimal("2.00")))
        AltitudeArea.recalculate()
        self._assertAltitudeAreas({
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("2.00"), geometry=box(0, 0, 110, 100)),
        })

    def test_simple_ramp(self):
        level = self._create_level()
        space = self._create_space(level)
        Stair.objects.create(space=space, geometry=LineString([(10, -1), (10, 101)]))
        Ramp.objects.create(space=space, geometry=box(20, -1, 80, 100))
        AltitudeMarker.objects.create(space=space, geometry=Point(11, 10),
                                      groundaltitude=GroundAltitude.objects.create(name="1", altitude=Decimal("1.00")))
        AltitudeMarker.objects.create(space=space, geometry=Point(90, 10),
                                      groundaltitude=GroundAltitude.objects.create(name="2", altitude=Decimal("2.00")))
        AltitudeMarker.objects.create(space=space, geometry=Point(1, 10),
                                      groundaltitude=GroundAltitude.objects.create(name="3", altitude=Decimal("3.00")))
        AltitudeArea.recalculate()
        self._assertAltitudeAreas({
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("3.00"), geometry=box(0, 0, 10, 100)),
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("1.00"), geometry=box(10, 0, 20, 100)),
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("2.00"), geometry=box(80, 0, 100, 100)),
            ExpectedAltitudeArea.new(
                level=level,
                points=frozenset((
                    AltitudeAreaPoint(coordinates=(20.0, 0.0), altitude=1.00),
                    AltitudeAreaPoint(coordinates=(20.0, 100.0), altitude=1.00),
                    AltitudeAreaPoint(coordinates=(80.0, 0.0), altitude=2.00),
                    AltitudeAreaPoint(coordinates=(80.0, 100.0), altitude=2.00),
                )),
                geometry=box(20, 0, 80, 100),
            )
        })

    def test_ramp_only_one_end(self):
        level = self._create_level()
        space = self._create_space(level)
        Ramp.objects.create(space=space, geometry=box(20, -1, 101, 100))
        AltitudeMarker.objects.create(space=space, geometry=Point(10, 10),
                                      groundaltitude=GroundAltitude.objects.create(name="1", altitude=Decimal("1.00")))
        AltitudeArea.recalculate()
        self._assertAltitudeAreas({
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("1.00"), geometry=box(0, 0, 100, 100)),
        })

    def test_ramp_two_identical_ends(self):
        level = self._create_level()
        space = self._create_space(level)
        Ramp.objects.create(space=space, geometry=box(20, -1, 80, 100))
        AltitudeMarker.objects.create(space=space, geometry=Point(10, 10),
                                      groundaltitude=GroundAltitude.objects.create(name="1a", altitude=Decimal("1.00")))
        AltitudeMarker.objects.create(space=space, geometry=Point(90, 10),
                                      groundaltitude=GroundAltitude.objects.create(name="1b", altitude=Decimal("1.00")))
        AltitudeArea.recalculate()
        self._assertAltitudeAreas({
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("1.00"), geometry=box(0, 0, 100, 100)),
        })

    def test_ramp_multiple_points(self):
        level = self._create_level()
        space = self._create_space(level)
        Ramp.objects.create(space=space, geometry=box(20, -1, 101, 100))
        AltitudeMarker.objects.create(space=space, geometry=Point(10, 10),
                                      groundaltitude=GroundAltitude.objects.create(name="1", altitude=Decimal("1.00")))
        AltitudeMarker.objects.create(space=space, geometry=Point(90, 10),
                                      groundaltitude=GroundAltitude.objects.create(name="2", altitude=Decimal("2.00")))
        AltitudeMarker.objects.create(space=space, geometry=Point(90, 90),
                                      groundaltitude=GroundAltitude.objects.create(name="3", altitude=Decimal("3.00")))
        AltitudeArea.recalculate()
        self._assertAltitudeAreas({
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("1.00"), geometry=box(0, 0, 20, 100)),
            ExpectedAltitudeArea.new(
                level=level,
                points=frozenset((
                    AltitudeAreaPoint(coordinates=(20.0, 0.0), altitude=1.00),
                    AltitudeAreaPoint(coordinates=(20.0, 100.0), altitude=1.00),
                    AltitudeAreaPoint(coordinates=(90.0, 10.0), altitude=2.00),
                    AltitudeAreaPoint(coordinates=(90.0, 90.0), altitude=3.00),
                )),
                geometry=box(20, 0, 100, 100),
            )
        })

    def test_ramp_only_no_markers(self):
        level = self._create_level()
        space = self._create_space(level)
        Ramp.objects.create(space=space, geometry=box(-1, -1, 101, 100))
        AltitudeArea.recalculate()
        self._assertAltitudeAreas({
            ExpectedAltitudeArea.new(level=level, altitude=self.altitude, geometry=box(0, 0, 100, 100)),
        })

    def test_ramp_surrounded_with_gap(self):
        level = self._create_level()
        space = self._create_space(level)
        Ramp.objects.create(space=space, geometry=box(-1, -1, 101, 100))
        space2_polygon = box(-10, -10, 110, 110).difference(box(-5, -5, 105, 105))
        space2 = Space.objects.create(level=level, geometry=space2_polygon)
        AltitudeMarker.objects.create(space=space2, geometry=Point(-6, -6),
                                      groundaltitude=GroundAltitude.objects.create(name="1", altitude=Decimal("1.00")))
        AltitudeArea.recalculate()
        self._assertAltitudeAreas({
            ExpectedAltitudeArea.new(level=level, altitude=Decimal("1.00"), geometry=space2_polygon),
            ExpectedAltitudeArea.new(level=level, altitude=self.altitude, geometry=box(0, 0, 100, 100)),
        })
