from decimal import Decimal

from django.test.testcases import TransactionTestCase
from shapely import normalize, Polygon

from c3nav.mapdata.models import AltitudeArea, Level, Space


class PolygonCuttingTests(TransactionTestCase):
    def test_no_data(self):
        AltitudeArea.recalculate()
        self.assertFalse(AltitudeArea.objects.exists())

    def test_level_no_spaces(self):
        Level.objects.create(
            base_altitude=13.7,
            short_label="0l",
            level_index="0i",
        )
        AltitudeArea.recalculate()
        self.assertFalse(AltitudeArea.objects.exists())

    def test_one_space_no_marker(self):
        altitude = Decimal("13.70")
        level = Level.objects.create(
            base_altitude=altitude,
            short_label="0l",
            level_index="0i",
        )
        space = Space.objects.create(
            level=level,
            geometry=Polygon([(0, 0), (100, 0), (100, 100), (0, 100)]),
        )
        AltitudeArea.recalculate()
        self.assertEqual(AltitudeArea.objects.count(), 1)

        area = AltitudeArea.objects.first()
        self.assertEqual(area.level, level)
        self.assertEqual(area.geometry, normalize(space.geometry))
        self.assertEqual(area.altitude, altitude)
        self.assertIsNone(area.points)
