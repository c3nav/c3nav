from typing import NamedTuple

from django.test.testcases import TransactionTestCase

from c3nav.mapdata import process
from c3nav.mapdata.models import AccessRestriction, Theme
from c3nav.mapdata.models.locations import LocationTag, LabelSettings


class LocationTagDirectionOrders(NamedTuple):
    breadth_first_order: tuple[LocationTag, ...]
    depth_first_pre_order: tuple[LocationTag, ...]
    depth_first_post_order: tuple[LocationTag, ...]


class ExpectedLocationTagOrderResult(NamedTuple):
    upwards: LocationTagDirectionOrders
    downwards: LocationTagDirectionOrders
    ancestors: dict[LocationTag, LocationTagDirectionOrders]
    descendants: dict[LocationTag, LocationTagDirectionOrders]


class LocationTagOrderTests(TransactionTestCase):
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
        process.process_location_tag_relations()
        for direction in ("downwards", "upwards"):
            for order_label in ("breadth_first_order", "depth_first_pre_order", "depth_first_post_order"):
                self.assertQuerySetEqual(
                    LocationTag.objects.order_by(f"effective_{direction}_{order_label}"),
                    getattr(getattr(expected, direction), order_label),
                    msg=f"{direction} {order_label.replace("_", " ")} doesn't match"
                )

        for relation, direction in (("ancestors", "upwards_relations__effective_downwards_"),
                                    ("descendants", "downwards_relations__effective_upwards_")):
            for tag, orders in getattr(expected, relation).items():
                for order_label in ("breadth_first_order", "depth_first_pre_order", "depth_first_post_order"):
                    self.assertQuerySetEqual(
                        getattr(tag, f"calculated_{relation}").order_by(f'{direction}_{order_label}'),
                        getattr(orders, order_label),
                        msg=f"{tag} {relation} {order_label.replace("_", " ")} doesn't match"
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
            downwards=LocationTagDirectionOrders(
                breadth_first_order=(singles[1], parent, singles[0], children[0], children[2], children[1]),
                depth_first_pre_order=(singles[1], parent, children[0], children[2], children[1], singles[0]),
                depth_first_post_order=(singles[1], children[0], children[2], children[1], parent, singles[0]),
            ),
            upwards=LocationTagDirectionOrders(
                breadth_first_order=(singles[1], children[0], singles[0], children[2], children[1], parent),
                depth_first_pre_order=(singles[1], children[0], parent, singles[0], children[2], children[1]),
                depth_first_post_order=(singles[1], parent, children[0], singles[0], children[2], children[1]),
            ),
            ancestors={},
            descendants={},
        ))
