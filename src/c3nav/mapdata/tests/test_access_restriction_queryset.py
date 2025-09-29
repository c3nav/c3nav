from django.test.testcases import TransactionTestCase
from shapely import Polygon, Point

from c3nav.mapdata.models import AccessRestriction, Level, Space, Area, POI
from c3nav.mapdata.permissions import active_map_permissions, ManualMapPermissions


class AccessRestrictionQueryset(TransactionTestCase):
    # todo: all api endpoints and ways to determine active permissions need to be tested separately

    def setUp(self):
        # Test definitions as before.
        self.restriction_1 = AccessRestriction.objects.create(titles={"en": "Restriction 1"})
        self.restriction_2 = AccessRestriction.objects.create(titles={"en": "Restriction 2"})
        self.restriction_3 = AccessRestriction.objects.create(titles={"en": "Restriction 3"})

    def _test_restriction(self, qs_func, objs_0: list, objs_1: list, objs_2: list, objs_3: list, objs_1_2: list):
        with active_map_permissions.override(ManualMapPermissions.get_full_access()):
            self.assertQuerySetEqual(qs_func(), objs_0 + objs_1 + objs_2 + objs_3 + objs_1_2, ordered=False)

        with active_map_permissions.override(ManualMapPermissions.get_public_access()):
            self.assertQuerySetEqual(qs_func(), objs_0, ordered=False)

        with active_map_permissions.override(ManualMapPermissions(access_restrictions={self.restriction_1.pk})):
            self.assertQuerySetEqual(qs_func(), objs_0 + objs_1, ordered=False)

        with active_map_permissions.override(ManualMapPermissions(access_restrictions={self.restriction_2.pk})):
            self.assertQuerySetEqual(qs_func(), objs_0 + objs_2, ordered=False)

        with active_map_permissions.override(ManualMapPermissions(access_restrictions={self.restriction_1.pk,
                                                                                       self.restriction_2.pk})):
            self.assertQuerySetEqual(qs_func(), objs_0 + objs_1 + objs_2 + objs_1_2, ordered=False)

    def test_level_restriction(self):
        level_0 = Level.objects.create(
            base_altitude=0,
            short_label="0l",
            level_index="0i",
            access_restriction=None,
        )
        level_1 = Level.objects.create(
            base_altitude=1,
            short_label="1l",
            level_index="1i",
            access_restriction=self.restriction_1,
        )
        level_2 = Level.objects.create(
            base_altitude=2,
            short_label="2l",
            level_index="2i",
            access_restriction=self.restriction_2,
        )
        level_3 = Level.objects.create(
            base_altitude=3,
            short_label="3l",
            level_index="3i",
            access_restriction=self.restriction_3,
        )

        self._test_restriction(lambda: Level.objects.all(),
                               [level_0], [level_1], [level_2], [level_3], [])

    def test_space_direct_restriction(self):
        level = Level.objects.create(
            base_altitude=0,
            short_label="0l",
            level_index="0i",
            access_restriction=None,
        )
        space_0 = Space.objects.create(
            level=level,
            geometry=Polygon([(0, 0), (0, 1), (1, 0)]),
            access_restriction=None,
        )
        space_1 = Space.objects.create(
            level=level,
            geometry=Polygon([(10, 0), (10, 1), (11, 0)]),
            access_restriction=self.restriction_1,
        )
        space_2 = Space.objects.create(
            level=level,
            geometry=Polygon([(20, 0), (20, 1), (21, 0)]),
            access_restriction=self.restriction_2,
        )
        space_3 = Space.objects.create(
            level=level,
            geometry=Polygon([(30, 0), (30, 1), (31, 0)]),
            access_restriction=self.restriction_3,
        )

        self._test_restriction(lambda: Space.objects.all(),
                               [space_0], [space_1], [space_2], [space_3], [])

    def test_area_direct_restriction(self):
        level = Level.objects.create(
            base_altitude=0,
            short_label="0l",
            level_index="0i",
            access_restriction=None,
        )
        space = Space.objects.create(
            level=level,
            geometry=Polygon([(0, 0), (100, 0), (100, 100), (0, 100)]),
            access_restriction=None,
        )
        area_0 = Area.objects.create(
            space=space,
            geometry=Polygon([(0, 0), (0, 1), (1, 0)]),
            access_restriction=None,
        )
        area_1 = Area.objects.create(
            space=space,
            geometry=Polygon([(10, 0), (10, 1), (11, 0)]),
            access_restriction=self.restriction_1,
        )
        area_2 = Area.objects.create(
            space=space,
            geometry=Polygon([(20, 0), (20, 1), (21, 0)]),
            access_restriction=self.restriction_2,
        )
        area_3 = Area.objects.create(
            space=space,
            geometry=Polygon([(30, 0), (30, 1), (31, 0)]),
            access_restriction=self.restriction_3,
        )

        self._test_restriction(lambda: Area.objects.all(),
                               [area_0], [area_1], [area_2], [area_3], [])

    def test_poi_direct_restriction(self):
        level = Level.objects.create(
            base_altitude=0,
            short_label="0l",
            level_index="0i",
            access_restriction=None,
        )
        space = Space.objects.create(
            level=level,
            geometry=Polygon([(0, 0), (100, 0), (100, 100), (0, 100)]),
            access_restriction=None,
        )
        poi_0 = POI.objects.create(
            space=space,
            geometry=Point((0.4, 0.4)),
            access_restriction=None,
        )
        poi_1 = POI.objects.create(
            space=space,
            geometry=Point((1.4, 0.4)),
            access_restriction=self.restriction_1,
        )
        poi_2 = POI.objects.create(
            space=space,
            geometry=Point((2.4, 0.4)),
            access_restriction=self.restriction_2,
        )
        poi_3 = POI.objects.create(
            space=space,
            geometry=Point((3.4, 0.4)),
            access_restriction=self.restriction_3,
        )

        self._test_restriction(lambda: POI.objects.all(),
                               [poi_0], [poi_1], [poi_2], [poi_3], [])

    def test_space_level_restriction(self):
        level_0 = Level.objects.create(
            base_altitude=0,
            short_label="0l",
            level_index="0i",
            access_restriction=None,
        )
        level_1 = Level.objects.create(
            base_altitude=1,
            short_label="1l",
            level_index="1i",
            access_restriction=self.restriction_1,
        )
        level_2 = Level.objects.create(
            base_altitude=2,
            short_label="2l",
            level_index="2i",
            access_restriction=self.restriction_2,
        )
        level_3 = Level.objects.create(
            base_altitude=3,
            short_label="3l",
            level_index="3i",
            access_restriction=self.restriction_3,
        )
        space_0 = Space.objects.create(
            level=level_0,
            geometry=Polygon([(0, 0), (0, 1), (1, 0)]),
            access_restriction=None,
        )
        space_1 = Space.objects.create(
            level=level_1,
            geometry=Polygon([(10, 0), (10, 1), (11, 0)]),
            access_restriction=None,
        )
        space_2 = Space.objects.create(
            level=level_2,
            geometry=Polygon([(10, 0), (10, 1), (11, 0)]),
            access_restriction=None,
        )
        space_3 = Space.objects.create(
            level=level_3,
            geometry=Polygon([(10, 0), (10, 1), (11, 0)]),
            access_restriction=None,
        )
        space_1_2 = Space.objects.create(
            level=level_1,
            geometry=Polygon([(10, 0), (10, 1), (11, 0)]),
            access_restriction=self.restriction_2,
        )

        self._test_restriction(lambda: Space.objects.all(),
                               [space_0], [space_1], [space_2], [space_3], [space_1_2])

    # todo: add more tests of this kind