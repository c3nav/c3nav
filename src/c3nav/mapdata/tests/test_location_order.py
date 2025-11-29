from typing import NamedTuple, Sequence

from django.test.testcases import TransactionTestCase

from c3nav.mapdata import process
from c3nav.mapdata.models import AccessRestriction, Theme
from c3nav.mapdata.models.locations import LocationTag, LabelSettings
from c3nav.mapdata.permissions import active_map_permissions


class ExpectedLocationTagOrderResult(NamedTuple):
    # root: Sequence[LocationTag]  # todo
    descendants: dict[LocationTag, Sequence[LocationTag]] = None
    ancestors: dict[LocationTag, Sequence[LocationTag]] = None


class LocationTagOrderTests(TransactionTestCase):
    # todo: more tests for this stuff

    # todo: count queries
    def setUp(self):
        LocationTag.objects.all().delete()
        self.access_restriction = AccessRestriction.objects.create(titles={"en": "Restriction 1"})
        self.label_settings = LabelSettings.objects.create()
        self.theme = Theme.objects.create(description="MyTheme")

    def _create_tag(self, name, priority: int) -> LocationTag:
        return LocationTag.objects.create(priority=priority, titles={"en": name})

    def _create_tags(self, name, priorities: tuple[int, ...]) -> list[LocationTag]:
        return LocationTag.objects.bulk_create((
            LocationTag(priority=priority, titles={"en": f"{name}{i}"})
            for i, priority in enumerate(priorities, start=1)
        ))

    def _recalculate(self):
        with active_map_permissions.disable_access_checks():  # todo: have the permissions thing be part of the tasks?
            process.recalculate_locationtag_effective_inherited_values()

    def assertLocationOrder(self, expected: ExpectedLocationTagOrderResult):
        self._recalculate()
        tag_by_id = {tag.pk: tag for tag in LocationTag.objects.all()}
        for direction in ("ancestors", "descendants"):
            for tag, orders in (getattr(expected, direction) or {}).items():
                self.assertListEqual(list(getattr(tag_by_id[tag.pk], direction)), [t.pk for t in orders])

    def test_triple_tree_and_two_singles(self):
        """
                parent(5)          single1(3)      single(6)
               /    |    \
        child(3) child(1) child(2)
        """
        parent = self._create_tag("parent", 5)
        children = self._create_tags("child", (3, 1, 2))
        singles = self._create_tags("single", (3, 6))
        for child in children:
            child.parents.add(parent)

        self.assertLocationOrder(ExpectedLocationTagOrderResult(
            descendants={
                parent: [children[0], children[2], children[1]],
            },
        ))

    def test_two_lines(self):
        r"""
        parent(1)  parent(0)
            |          |
         child(2)   child(3)
        """
        parents = self._create_tags("parent", (1, 0))
        children = self._create_tags("child", (2, 3))
        for parent, child in zip(parents, children):
            child.parents.add(parent)

        self.assertLocationOrder(ExpectedLocationTagOrderResult(
            descendants={
                parents[0]: [children[0]],
                parents[1]: [children[1]],
            },
        ))

    def test_quad_and_two_singles(self):
        r"""
                 sup(6)
         --------/  / \
        /          /   \
        |  parent(4)   parent(5)
         \          \ /
          \      ----+----
           \    /    |    \
        child(7) child(1)  child(2)
        """
        sup = self._create_tag("superparent", 6)
        parents = self._create_tags("parent", (4, 5))
        children = self._create_tags("child", (7, 1, 2))
        for parent in parents:
            parent.parents.add(sup)
            for child in children:
                child.parents.add(parent)
        children[0].parents.add(sup)

        self.assertLocationOrder(ExpectedLocationTagOrderResult(
            descendants={
                sup: [children[0], parents[1], children[2], children[1], parents[0]],
                parents[0]: [children[0], children[2], children[1]],
                parents[1]: [children[0], children[2], children[1]],
            },
        ))