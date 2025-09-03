from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from shapely import Point
from shapely.geometry import mapping

from c3nav.mapdata.models.geometry.space import RangingBeacon
from c3nav.mapdata.quests.base import ChangeSetModelForm, register_quest, Quest
from c3nav.mapdata.quests.positioning import RangingBeaconBSSIDsQuestForm


class RangingBeaconMarvelQuestForm(ChangeSetModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def clean(self):
        raise ValidationError(_("You have not marveled enough yet! Marvel more!"))

    class Meta:
        model = RangingBeacon
        fields = ()

    @property
    def changeset_title(self):
        return f'Ranging Beacon BSSID Quest: {self.instance.title}'


@register_quest
@dataclass
class RangingBeaconMarvelQuest(Quest):
    quest_type = "event_wifi_ack"
    quest_type_label = _('Wifi AP Marveling')
    quest_type_icon = "wifi_proxy"
    form_class = RangingBeaconBSSIDsQuestForm
    obj: RangingBeacon

    @property
    def quest_description(self) -> list[str]:
        return [
            _("Marvel at this access point with the name: %s") % self.obj.title,
            _("Marvel at its addresses: %s") % self.obj.addresses,
            _("Marvel at its bluetooth addresses: %s") % self.obj.bluetooth_address,
            _("Marvel at its BLE addresses: %s %s %s") % (self.obj.ibeacon_uuid,
                                                          self.obj.ibeacon_major,
                                                          self.obj.ibeacon_minor),
            _("Your time starts now."),
        ]

    @property
    def point(self) -> Point:
        return mapping(self.obj.geometry)

    @classmethod
    def _qs_for_request(cls, request):
        return RangingBeacon.qs_for_request(request).filter(beacon_type=RangingBeacon.BeaconType.EVENT_WIFI)
