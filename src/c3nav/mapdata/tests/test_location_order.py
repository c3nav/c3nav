from typing import NamedTuple

from django.test.testcases import TransactionTestCase
from django.db.models import OuterRef, Subquery

from c3nav.mapdata import process
from c3nav.mapdata.models import AccessRestriction, Theme
from c3nav.mapdata.models.locations import LocationTag, LabelSettings
from c3nav.mapdata.permissions import active_map_permissions


'''

class LocationTagDirectionOrders(NamedTuple):
    breadth_first_order: tuple[LocationTag, ...]
    depth_first_pre_order: tuple[LocationTag, ...]
    depth_first_post_order: tuple[LocationTag, ...]

    @classmethod
    def none(cls):
        return cls((), (), ())

    @classmethod
    def all(cls, order: tuple[LocationTag, ...]):
        return cls(order, order, order)


class ExpectedLocationTagOrderResult(NamedTuple):
    root: LocationTagDirectionOrders
    descendants: dict[LocationTag, LocationTagDirectionOrders]


class LocationTagOrderTests(TransactionTestCase):
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

    def assertLocationOrder(self, expected: ExpectedLocationTagOrderResult):
        with active_map_permissions.disable_access_checks():  # todo: have the permissions thing be part of the tasks?
            pass # pass
        for order_label in ("breadth_first_order", "depth_first_pre_order", "depth_first_post_order"):
            field_name = f"effective_{order_label}"
            subquery = LocationTagRelation.objects.filter(ancestor=None, descendant=OuterRef("pk")).order_by(field_name)
            from pprint import pprint
            print(field_name)
            pprint(list(LocationTagRelation.objects.filter(ancestor=None).order_by(field_name).values("pk", "ancestor", "descendant", "prev_relation", field_name)))
            self.assertQuerySetEqual(
                LocationTag.objects.annotate(
                    **{field_name: Subquery(subquery.values(field_name)[:1])}
                ).order_by(field_name),
                getattr(expected.root, order_label),
                msg=f"root {order_label.replace("_", " ")} doesn't match"
            )

        for tag, orders in getattr(expected, "descendants").items():
            for order_label in ("breadth_first_order", "depth_first_pre_order", "depth_first_post_order"):
                #print("order_by", f'{direction}_{order_label}')
                self.assertQuerySetEqual(
                    getattr(tag, f"calculated_descendants").distinct().order_by(f'upwards_relations__effective_{order_label}'),
                    getattr(orders, order_label),
                    msg=f"{tag!r} descendants {order_label.replace("_", " ")} doesn't match: ()"
                )

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
            root=LocationTagDirectionOrders(
                breadth_first_order=(singles[1], parent, singles[0], children[0], children[2], children[1]),
                depth_first_pre_order=(singles[1], parent, children[0], children[2], children[1], singles[0]),
                depth_first_post_order=(singles[1], children[0], children[2], children[1], parent, singles[0]),
            ),
            descendants={
                parent: LocationTagDirectionOrders.all((children[0], children[2], children[1])),
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
            root=LocationTagDirectionOrders(
                breadth_first_order=(parents[0], parents[1], children[0], children[1]),
                depth_first_pre_order=(parents[0], children[0], parents[1], children[1]),
                depth_first_post_order=(children[0], parents[0], children[1], parents[1]),
            ),
            descendants={
                parents[0]: LocationTagDirectionOrders.all((children[0],)),
                parents[1]: LocationTagDirectionOrders.all((children[1],)),
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
            root=LocationTagDirectionOrders(
                breadth_first_order=(sup, children[0], parents[1], parents[0], children[2], children[1]),
                depth_first_pre_order=(sup, children[0], parents[1], children[2], children[1], parents[0]),
                depth_first_post_order=(children[0], children[2], children[1], parents[1], parents[0], sup),
            ),
            descendants={
                sup: LocationTagDirectionOrders(
                    breadth_first_order=(children[0], parents[1], parents[0], children[2], children[1]),
                    depth_first_pre_order=(children[0], parents[1], children[2], children[1], parents[0]),
                    depth_first_post_order=(children[0], children[2], children[1], parents[1], parents[0]),
                ),
                parents[0]: LocationTagDirectionOrders.all((children[0], children[2], children[1])),
                parents[1]: LocationTagDirectionOrders.all((children[0], children[2], children[1])),
            },
        ))


'''