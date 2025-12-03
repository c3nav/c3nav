from django.test.testcases import TransactionTestCase

from c3nav.mapdata import process
from c3nav.mapdata.models import AccessRestriction, Theme, Level
from c3nav.mapdata.models.locations import LocationTag, LabelSettings, CircularHierarchyError
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
            process.recalculate_locationtag_effective_inherited_values()

    def test_circular_fails(self):
        """
        Create three location tags and turn them into a chain.
        Try to add the bottom one as a parent to the top one, creating a circle. This needs to fail.
        """
        locations = LocationTag.objects.bulk_create((
            LocationTag(),
            LocationTag(),
            LocationTag(),
        ))
        locations[0].children.add(locations[1])
        locations[1].children.add(locations[2])
        with self.assertRaises(CircularHierarchyError):
            locations[2].children.add(locations[0])

    def test_single_tag(self):
        tag = LocationTag.objects.create(
            icon="testicon",
        )
        level = Level.objects.create(short_label="level0", level_index="0", base_altitude=0)
        tag.levels.add(level)
        self._recalculate()

        tag.refresh_from_db()
        self.assertEqual(tag.effective_icon, "testicon")
        self.assertEqual(tag.effective_external_url_labels, {})
        self.assertIsNone(tag.effective_label_settings_id, None)
        self.assertEqual(tag.get_color(ColorManager.for_theme(theme=None)), None)
        self.assertEqual(tag.get_color(ColorManager.for_theme(theme=self.theme)), None)
        self.assertEqual(tag.inherited.describing_title, [])
        self.assertEqual(str(tag.describing_title), "")

        # todo: this stuff could belong somewhere else
        level.refresh_from_db()
        self.assertEqual(level.get_color(ColorManager.for_theme(theme=None)), None)
        self.assertEqual(level.get_color(ColorManager.for_theme(theme=self.theme)), None)
        self.assertEqual(list(level.sorted_tag_ids), [tag.pk])

        new_tag = LocationTag.objects.create(
            external_url_labels={"en": "Testlabel"},
            label_settings=self.label_settings,
            color="#ff0000",
        )
        new_tag.levels.add(level)
        self.theme.tags.create(tag=new_tag, fill_color="#00ff00")
        self._recalculate()

        new_tag.refresh_from_db()
        self.assertIsNone(new_tag.effective_icon)
        self.assertEqual(new_tag.effective_external_url_labels, {"en": "Testlabel"})
        self.assertEqual(new_tag.effective_label_settings_id, self.label_settings.pk)
        self.assertEqual(new_tag.get_color(ColorManager.for_theme(theme=None)), "#ff0000")
        self.assertEqual(new_tag.get_color(ColorManager.for_theme(theme=self.theme)), "#00ff00")
        self.assertEqual(new_tag.inherited.describing_title, [])
        self.assertEqual(str(new_tag.describing_title), "")

        # todo: this stuff could belong somewhere else
        level = Level.objects.get(pk=level.pk)  # need reload, because cached_property
        self.assertEqual(level.get_color(ColorManager.for_theme(theme=None)), "#ff0000")
        self.assertEqual(level.get_color(ColorManager.for_theme(theme=self.theme)), "#00ff00")
        self.assertEqual(list(level.sorted_tag_ids), [tag.pk, new_tag.pk])

        new_tag.levels.remove(level)
        self._recalculate()

        # todo: this stuff could belong somewhere else
        level = Level.objects.get(pk=level.pk)  # need reload, because cached_property
        self.assertEqual(level.get_color(ColorManager.for_theme(theme=None)), None)
        self.assertEqual(level.get_color(ColorManager.for_theme(theme=self.theme)), None)
        self.assertEqual(list(level.sorted_tag_ids), [tag.pk])

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
        self.assertEqual(tag.inherited.describing_title, [])
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
            tag = LocationTag.objects.get(pk=tag.pk)  # need reload, because cached_property
            self.assertEqual(tag.effective_icon, "child1icon")
            self.assertEqual(tag.effective_external_url_labels, {"en": "child1urllabel"})
            self.assertEqual(tag.effective_label_settings_id, label_settings[2].pk)
            self.assertEqual(tag.get_color(ColorManager.for_theme(theme=None)), "child1color")

        with active_map_permissions.override(ManualMapPermissions()):
            tag = LocationTag.objects.get(pk=tag.pk)  # need reload, because cached_property
            self.assertEqual(tag.effective_icon, "child2icon")
            self.assertEqual(tag.effective_external_url_labels, {"en": "child2urllabel"})
            self.assertEqual(tag.effective_label_settings_id, label_settings[3].pk)
            self.assertEqual(tag.get_color(ColorManager.for_theme(theme=None)), "child2color")

        tag.icon = "newicon"
        tag.save()
        self._recalculate()
        with active_map_permissions.override(ManualMapPermissions()):
            tag = LocationTag.objects.get(pk=tag.pk)  # need reload, because cached_property
            self.assertEqual(tag.effective_icon, "newicon")

        tag.external_url_labels = {"en": "newlabel"}
        tag.save()
        self._recalculate()
        with active_map_permissions.override(ManualMapPermissions()):
            tag = LocationTag.objects.get(pk=tag.pk)  # need reload, because cached_property
            self.assertEqual(tag.effective_external_url_labels, {"en": "newlabel"})

        tag.label_settings = label_settings[4]
        tag.save()
        self._recalculate()
        with active_map_permissions.override(ManualMapPermissions()):
            tag = LocationTag.objects.get(pk=tag.pk)  # need reload, because cached_property
            self.assertEqual(tag.effective_label_settings_id, label_settings[4].pk)

        tag.color = "newcolor"
        tag.save()
        self._recalculate()
        with active_map_permissions.override(ManualMapPermissions()):
            tag = LocationTag.objects.get(pk=tag.pk)  # need reload, because cached_property
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
            self.assertEqual(str(tag.describing_title), "Child 2",
                             msg="Describing title without access permission doesn't match")

    def test_location_tag_hidden_if_no_inherited(self):
        tag = LocationTag.objects.create(titles={"en": "Tag"}, priority=1)

        with active_map_permissions.override(ManualMapPermissions()):
            self.assertQuerySetEqual(LocationTag.objects.filter(pk=tag.pk), [])

        with active_map_permissions.override(ManualMapPermissions(access_restrictions={self.access_restriction.pk})):
            self.assertQuerySetEqual(LocationTag.objects.filter(pk=tag.pk), [])

        with active_map_permissions.override(ManualMapPermissions.get_full_access()):
            self.assertQuerySetEqual(LocationTag.objects.filter(pk=tag.pk), [tag])

        self._recalculate()

        with active_map_permissions.override(ManualMapPermissions()):
            self.assertQuerySetEqual(LocationTag.objects.filter(pk=tag.pk), [tag])

        with active_map_permissions.override(ManualMapPermissions(access_restrictions={self.access_restriction.pk})):
            self.assertQuerySetEqual(LocationTag.objects.filter(pk=tag.pk), [tag])

        with active_map_permissions.override(ManualMapPermissions.get_full_access()):
            self.assertQuerySetEqual(LocationTag.objects.filter(pk=tag.pk), [tag])
