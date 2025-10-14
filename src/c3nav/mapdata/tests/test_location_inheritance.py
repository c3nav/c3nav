from django.test.testcases import TransactionTestCase

from c3nav.mapdata import process
from c3nav.mapdata.models import AccessRestriction, Theme
from c3nav.mapdata.models.locations import LocationTag, LabelSettings
from c3nav.mapdata.render.theme import ColorManager


class LocationInheritanceTests(TransactionTestCase):
    def setUp(self):
        self.access_restriction = AccessRestriction.objects.create(titles={"en": "Restriction 1"})
        self.label_settings = LabelSettings.objects.create()
        self.theme = Theme.objects.create(description="MyTheme")

    def _recalculate(self):
        process.process_location_tag_relations()
        LocationTag.recalculate_cached_from_parents()

    def test_single_tag(self):
        tag = LocationTag.objects.create(
            icon="testicon",
        )
        self._recalculate()
        tag.refresh_from_db()

        self.assertEqual(tag.effective_icon, "testicon")
        self.assertEqual(tag.effective_external_url_labels, {})
        self.assertIsNone(tag.effective_label_settings, None)
        self.assertEqual(tag.get_color(ColorManager.for_theme(theme=None)), None)
        self.assertEqual(tag.get_color(ColorManager.for_theme(theme=self.theme)), None)
        self.assertEqual(tag.cached_describing_titles, [])
        self.assertEqual(str(tag.describing_title), "")

        tag = LocationTag.objects.create(
            external_url_labels={"en": "Testlabel"},
            label_settings=self.label_settings,
            color="#ff0000",
        )
        self.theme.tags.create(tag=tag, fill_color="#00ff00")
        self._recalculate()
        tag.refresh_from_db()

        self.assertIsNone(tag.effective_icon)
        self.assertEqual(tag.effective_external_url_labels, {"en": "Testlabel"})
        self.assertEqual(tag.effective_label_settings_id, self.label_settings.pk)
        self.assertEqual(tag.get_color(ColorManager.for_theme(theme=None)), "#ff0000")
        self.assertEqual(tag.get_color(ColorManager.for_theme(theme=self.theme)), "#00ff00")
        self.assertEqual(tag.cached_describing_titles, [])
        self.assertEqual(str(tag.describing_title), "")

    def test_simple_inheritance(self):
        parent_tag = LocationTag.objects.create(
            icon="testicon",
            external_url_labels={"en": "Testlabel"},
            label_settings=self.label_settings,
            color="#ff0000",
        )
        self.theme.tags.create(tag=parent_tag, fill_color="#00ff00")
        tag = LocationTag.objects.create()
        tag.parents.add(parent_tag)
        self._recalculate()
        tag.refresh_from_db()

        self.assertEqual(tag.effective_icon, "testicon")
        self.assertEqual(tag.effective_external_url_labels, {"en": "Testlabel"})
        self.assertEqual(tag.effective_label_settings_id, self.label_settings.pk)
        self.assertEqual(tag.get_color(ColorManager.for_theme(theme=None)), "#ff0000")
        self.assertEqual(tag.get_color(ColorManager.for_theme(theme=self.theme)), "#00ff00")
        self.assertEqual(tag.cached_describing_titles, [])
        self.assertEqual(str(tag.describing_title), "")

    """
    Describing titles
    """

    def test_describing_titles_one_parent(self):
        parent1_tag = LocationTag.objects.create(titles={"en": "Parent 1"})
        tag = LocationTag.objects.create()
        tag.parents.add(parent1_tag)
        self._recalculate()
        tag.refresh_from_db()

        self.assertEqual(str(tag.describing_title), "Parent 1")

    def test_describing_titles_two_parents(self):
        parent1_tag = LocationTag.objects.create(titles={"en": "Parent 1"})
        parent2_tag = LocationTag.objects.create(titles={"de": "Parent 2"})
        tag = LocationTag.objects.create()
        tag.parents.add(parent1_tag)
        tag.parents.add(parent2_tag)
        self._recalculate()
        tag.refresh_from_db()

        self.assertEqual(str(tag.describing_title), "Parent 1")

    def test_describing_titles_two_parents_priority_in_order(self):
        parent1_tag = LocationTag.objects.create(titles={"en": "Parent 1"}, priority=0)
        parent2_tag = LocationTag.objects.create(titles={"de": "Parent 2"}, priority=1)
        tag = LocationTag.objects.create()
        tag.parents.add(parent1_tag)
        tag.parents.add(parent2_tag)
        self._recalculate()
        tag.refresh_from_db()

        self.assertEqual(str(tag.describing_title), "Parent 2")

    def test_describing_titles_two_parents_priority_not_in_order(self):
        parent1_tag = LocationTag.objects.create(titles={"en": "Parent 1"}, priority=1)
        parent2_tag = LocationTag.objects.create(titles={"de": "Parent 2"}, priority=0)
        tag = LocationTag.objects.create()
        tag.parents.add(parent1_tag)
        tag.parents.add(parent2_tag)
        self._recalculate()
        tag.refresh_from_db()

        self.assertEqual(str(tag.describing_title), "Parent 1")
