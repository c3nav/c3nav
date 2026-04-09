from django.db import transaction
from django.test.client import Client
from django.test.testcases import TestCase
from shapely import box

from c3nav.mapdata.models import AccessRestriction, Level, Space, Building, MapUpdate
from c3nav.mapdata.tests.base import override_path_settings
from c3nav.mapdata.updatejobs import run_mapupdate_jobs


class APILocationDisplayTest(TestCase):
    def setUp(self):
        self.access_restriction = AccessRestriction.objects.create(titles={"en": "Restriction 1"})
        self.client = Client()

    def test_map_settings(self):
        with self.settings(INITIAL_BOUNDS=None):
            r = self.client.get("/api/v2/map/settings/", headers={"X-API-Key": "anonymous"})
            self.assertEqual(200, r.status_code)

        with self.settings(INITIAL_BOUNDS=(-10, -20, 10, 20)):
            r = self.client.get("/api/v2/map/settings/", headers={"X-API-Key": "anonymous"})
            self.assertEqual(200, r.status_code)

    @override_path_settings()
    def test_map_bounds(self):
        r = self.client.get("/api/v2/map/bounds/", headers={"X-API-Key": "anonymous"})
        self.assertEqual(200, r.status_code)
        self.assertEqual(b'{"bounds": [[0.0, 0.0], [10.0, 10.0]]}', r.content)
        first_etag = r.headers["ETag"]

        level = Level.objects.create(
            base_altitude=0,
            short_label="0l",
            level_index="0i",
        )
        Space.objects.create(
            level=level,
            geometry=box(-10, -20, 100, 110),
            outside=True,
        )
        Building.objects.create(
            level=level,
            geometry=box(0, 0, 80, 200),
        )

        with self.captureOnCommitCallbacks(execute=True):
            MapUpdate.objects.create(type='management', geometries_changed=True, purge_all_cache=True)

        with self.captureOnCommitCallbacks(execute=True):
            run_mapupdate_jobs()

        self.client = Client()
        r = self.client.get("/api/v2/map/bounds/", headers={"X-API-Key": "anonymous"})
        self.assertEqual(200, r.status_code)
        self.assertNotEqual(first_etag, r.headers["ETag"])
        self.assertEqual(b'{"bounds": [[-10.0, -20.0], [100.0, 200.0]]}', r.content)