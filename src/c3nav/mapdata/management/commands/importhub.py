from uuid import UUID

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from pydantic import Field, BaseModel
from pydantic import PositiveInt

from c3nav.api.utils import NonEmptyStr


class HubImportItem(BaseModel):
    """
    Something imported from the hub
    """
    type: NonEmptyStr
    id: UUID
    slug: NonEmptyStr = Field(pattern=r'^[-a-zA-Z0-9_]+$')
    name: NonEmptyStr | dict[NonEmptyStr, NonEmptyStr]
    is_official: bool
    description: dict[NonEmptyStr, NonEmptyStr | None]
    public_url: NonEmptyStr = Field(pattern=r'^https://')
    parent_id: UUID | None
    children: list[NonEmptyStr] | None
    floor: PositiveInt
    location: tuple[float, float]
    polygons: tuple[list[tuple[float, float]]] | None


class Command(BaseCommand):
    help = 'import from hub'

    def handle(self, *args, **options):
        r = requests.get(settings.HUB_API_BASE+"/integration/c3nav",
                         headers={"Authorization": "Token "+settings.HUB_API_SECRET})
        r.raise_for_status()
        from pprint import pprint

        data = [
            {
                "type": "assembly",
                "id": "037c0b9c-6283-42e4-9c43-24e072e8718e",
                "slug": "fnord",
                "name": "Fnord Example Habitat",
                "is_official": False,
                "description": {
                    "de": "Beispiel Habitat",
                    "en": "Example Cluster"
                },
                "public_url": "https://hub.example.net/assembly/fnord/",
                "parent_id": None,
                "children": ["child"],
                "floor": 2,
                "location": [
                    13.301537039641516,
                    53.03217295491487
                ],
                "polygons": [
                    [
                        [
                            13.307995798949293,
                            53.03178583543769
                        ],
                        [
                            13.30780267990096,
                            53.030276036273506
                        ],
                        [
                            13.310034277800554,
                            53.03009537300366
                        ],
                        [
                            13.310205939178047,
                            53.0315793702961
                        ],
                        [
                            13.307995798949293,
                            53.03178583543769
                        ]
                    ]
                ]
            },
            {
                "type": "assembly",
                "id": "085657cc-9b46-4a71-853c-70e10a371e57",
                "slug": "kika",
                "name": "Kinderkanal",
                "is_official": True,
                "description": {
                    "de": "Danke für deinen Betrag.",
                    "en": "Thanks for your support."
                },
                "public_url": "https://hub.example.net/assembly/kika/",
                "parent_id": None,
                "children": None,
                "floor": 62,
                "location": [
                    13.300807478789807,
                    53.032327801732634
                ],
                "polygons": None
            },
            {
                "type": "assembly",
                "id": "fa1f2c57-fd54-47e6-add4-e483654b6741",
                "slug": "child",
                "name": "Assembly des Habitats #23",
                "is_official": False,
                "description": {
                    "de": None,
                    "en": "Sometimes, an example is all you get."
                },
                "public_url": "https://hub.example.net/assembly/child/",
                "parent_id": "037c0b9c-6283-42e4-9c43-24e072e8718e",
                "children": None,
                "floor": 2,
                "location": [
                    12.997614446551779,
                    53.040472311905404
                ],
                "polygons": [
                    [
                        [
                            13.308124544982434,
                            53.03139871248601
                        ],
                        [
                            13.308231833342973,
                            53.03173421924521
                        ],
                        [
                            13.309240343932686,
                            53.03166969891683
                        ],
                        [
                            13.309197428588305,
                            53.031218053919105
                        ],
                        [
                            13.308146002654183,
                            53.03123095812731
                        ],
                        [
                            13.308124544982434,
                            53.03139871248601
                        ]
                    ]
                ]
            }
        ]

        items: list[HubImportItem] = [HubImportItem.model_validate(item) for item in data]
        items_by_id = {item.id: item for item in items}

        for item in items:
            hub_types = [
                item.type,
                "%s:%s" % (item.type, f"parent:{items_by_id[item.parent_id].slug}" if item.parent_id else "no-parent")
            ]
            print(hub_types)
        pprint(r.json())