from django.test.testcases import TransactionTestCase

from c3nav.mapdata import process
from c3nav.mapdata.models import AccessRestriction, Theme
from c3nav.mapdata.models.locations import LocationTag, LabelSettings
from c3nav.mapdata.permissions import active_map_permissions, ManualMapPermissions
from c3nav.mapdata.render.theme import ColorManager


class LocationInheritanceTests(TransactionTestCase):
    # todo: count queries
    def setUp(self):
        self.access_restriction = AccessRestriction.objects.create(titles={"en": "Restriction 1"})
        self.label_settings = LabelSettings.objects.create()
        self.theme = Theme.objects.create(description="MyTheme")

    def _recalculate(self):
        with active_map_permissions.disable_access_checks():  # todo: have the permissions thing be part of the tasks?
            process.process_location_tag_relations()
            process.recalculate_locationtag_cached_from_parents()

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

    def test_complex_inheritance(self):
        label_settings = LabelSettings.objects.bulk_create([LabelSettings() for i in range(5)])
        parent1_tag, parent2_tag, child1_tag, child2_tag = tuple(
            LocationTag.objects.create(
                icon=f"{label}icon",
                external_url_labels={"en": f"{label}urllabel"},
                label_settings=label_settings[i],
                color=f"{label}color",
                access_restriction=access_restriction,
            ) for i, (label, access_restriction) in enumerate((("parent1", None),
                                                               ("parent2", None),
                                                               ("child1", self.access_restriction),
                                                               ("child2", None)))
        )
        child1_tag.parents.add(parent1_tag)
        child2_tag.parents.add(parent2_tag)

        tag = LocationTag.objects.create()
        tag.parents.add(child1_tag)
        tag.parents.add(child2_tag)
        self._recalculate()

        with active_map_permissions.override(ManualMapPermissions(access_restrictions={self.access_restriction.pk})):
            tag = LocationTag.objects.get(pk=tag.pk)  # need to reload, because cached_property
            self.assertEqual(tag.effective_icon, "child1icon")
            self.assertEqual(tag.effective_external_url_labels, {"en": "child1urllabel"})
            self.assertEqual(tag.effective_label_settings_id, label_settings[2].pk)
            self.assertEqual(tag.get_color(ColorManager.for_theme(theme=None)), "child1color")

        # todo: feature for the future?
        #with active_map_permissions.override(ManualMapPermissions()):
        #    tag = LocationTag.objects.get(pk=tag.pk)  # need to reload, because cached_property
        #    self.assertEqual(tag.effective_icon, "parent1icon")
        #    self.assertEqual(tag.effective_external_url_labels, {"en": "parent1urllabel"})
        #    self.assertEqual(tag.effective_label_settings_id, label_settings[0].pk)
        #    self.assertEqual(tag.get_color(ColorManager.for_theme(theme=None)), "parent1color")

        tag.icon = "newicon"
        tag.save()
        self._recalculate()
        with active_map_permissions.override(ManualMapPermissions()):
            tag = LocationTag.objects.get(pk=tag.pk)  # need to reload, because cached_property
            self.assertEqual(tag.effective_icon, "newicon")

        tag.external_url_labels = {"en": "newlabel"}
        tag.save()
        self._recalculate()
        with active_map_permissions.override(ManualMapPermissions()):
            tag = LocationTag.objects.get(pk=tag.pk)  # need to reload, because cached_property
            self.assertEqual(tag.effective_external_url_labels, {"en": "newlabel"})

        tag.label_settings = label_settings[4]
        tag.save()
        self._recalculate()
        with active_map_permissions.override(ManualMapPermissions()):
            tag = LocationTag.objects.get(pk=tag.pk)  # need to reload, because cached_property
            self.assertEqual(tag.effective_label_settings_id, label_settings[4].pk)

        tag.color = "newcolor"
        tag.save()
        self._recalculate()
        with active_map_permissions.override(ManualMapPermissions()):
            tag = LocationTag.objects.get(pk=tag.pk)  # need to reload, because cached_property
            self.assertEqual(tag.get_color(ColorManager.for_theme(theme=None)), "newcolor")

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

    def test_describing_titles_two_level_tree_with_permissions(self):
        parent1_tag = LocationTag.objects.create(titles={"en": "Parent 1"}, priority=1)
        parent2_tag = LocationTag.objects.create(titles={"de": "Parent 2"}, priority=0)
        child1_tag = LocationTag.objects.create(titles={"de": "Child 1"}, priority=2,
                                                access_restriction=self.access_restriction)
        child2_tag = LocationTag.objects.create(titles={"de": "Child 2"}, priority=3)
        child1_tag.parents.add(parent1_tag)
        child2_tag.parents.add(parent2_tag)
        tag = LocationTag.objects.create()
        tag.parents.add(child1_tag)
        tag.parents.add(child2_tag)
        self._recalculate()

        with active_map_permissions.override(ManualMapPermissions(access_restrictions={self.access_restriction.pk})):
            tag = LocationTag.objects.get(pk=tag.pk)  # need to reload, because cached_property
            self.assertEqual(str(tag.describing_title), "Child 1",
                             msg="Describing title with access permission doesn't match")

        with active_map_permissions.override(ManualMapPermissions()):
            tag = LocationTag.objects.get(pk=tag.pk)  # need to reload, because cached_property
            self.assertEqual(str(tag.describing_title), "Parent 1",
                             msg="Describing title without access permission doesn't match")
