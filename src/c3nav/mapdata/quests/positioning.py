from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.forms import CharField, HiddenInput
from django.utils.translation import gettext_lazy as _
from shapely import Point
from shapely.geometry import mapping

from c3nav.mapdata.models.geometry.space import RangingBeacon, BeaconMeasurement
from c3nav.mapdata.quests.base import ChangeSetModelForm, register_quest, Quest
from c3nav.routing.schemas import BeaconMeasurementDataSchema


class RangingBeaconAltitudeQuestForm(ChangeSetModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["altitude"].label = (
            _('How many meters above ground is “%s” mounted?') % self.instance.title
        )

    def clean_altitude(self):
        data = self.cleaned_data["altitude"]
        if not data:
            raise ValidationError(_("The device should not be 0m above ground."))
        return data

    class Meta:
        model = RangingBeacon
        fields = ("altitude", )

    def save(self, *args, **kwargs):
        self.instance.altitude_quest = False
        return super().save(*args, **kwargs)

    @property
    def changeset_title(self):
        return f'Altitude Quest: {self.instance.title}'


@register_quest
@dataclass
class RangingBeaconAltitudeQuest(Quest):
    quest_type = "ranging_beacon_altitude"
    quest_type_label = _('Ranging Beacon Altitude')
    quest_type_icon = "router"
    form_class = RangingBeaconAltitudeQuestForm
    obj: RangingBeacon

    @property
    def point(self) -> Point:
        return mapping(self.obj.geometry)

    @classmethod
    def _qs_for_request(cls, request):
        return RangingBeacon.qs_for_request(request).select_related('space',
                                                                    'space__level').filter(altitude_quest=True)


class RangingBeaconBSSIDsQuestForm(ChangeSetModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["look_for_ap"] = CharField(disabled=True, initial=self.instance.ap_name, widget=HiddenInput())
        self.fields["addresses"].widget = HiddenInput()

    def clean_addresses(self):
        data = self.cleaned_data["addresses"]
        if not data:
            raise ValidationError(_("Need at least one bssid."))
        return data

    class Meta:
        model = RangingBeacon
        fields = ("addresses", )

    @property
    def changeset_title(self):
        return f'Ranging Beacon BSSID Quest: {self.instance.title}'


@register_quest
@dataclass
class RangingBeaconBSSIDsQuest(Quest):
    quest_type = "ranging_beacon_bssids"
    quest_type_label = _('Ranging Beacon Identifier')
    quest_type_icon = "wifi_find"
    form_class = RangingBeaconBSSIDsQuestForm
    obj: RangingBeacon

    @property
    def quest_description(self) -> list[str]:
        return [
            _("This quest only works in the app. It works fully automatically."),
            _("We are trying to find the BSSIDs broadcast by “%s”.") % self.obj.title,
            _("Please stand near “%s” and wait for the submit button to appear.") % self.obj.title,
            _("Do not close this popup until then."),
            _("This should happen within less than a minute."),
        ]

    @property
    def point(self) -> Point:
        return mapping(self.obj.geometry)

    @classmethod
    def _qs_for_request(cls, request):
        return RangingBeacon.qs_for_request(request).select_related('space', 'space__level').filter(
            ap_name__isnull=False,
            addresses=[],
            beacon_type=RangingBeacon.BeaconType.EVENT_WIFI
        )


class BeaconMeasurementQuestForm(ChangeSetModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["beacon_measurement_quest"] = CharField(disabled=True, initial='', widget=HiddenInput(), required=False)
        self.fields["data"].widget = HiddenInput()

    def clean_data(self):
        data = self.cleaned_data["data"]
        if not data:
            raise ValidationError(_("Need at least one scan."))
        return data

    class Meta:
        model = BeaconMeasurement
        fields = ("data", )

    def save(self, *args, **kwargs):
        self.instance.fill_quest = False
        return super().save(*args, **kwargs)

    @property
    def changeset_title(self):
        return f'Beacon Measurement Quest: {self.instance.title}'


@register_quest
@dataclass
class BeaconMeasurementQuest(Quest):
    quest_type = "beacon_measurement"
    quest_type_label = _('Wifi/BLE Positioning')
    quest_type_icon = "wifi"
    form_class = BeaconMeasurementQuestForm
    obj: BeaconMeasurement

    @property
    def quest_description(self) -> list[str]:
        return [
            _("Please stand as close to the given location as possible. "
              "Feel free to close this window again to double-check."),
            _("When you're ready, please click the button below and wait for measurements to arrive."),
        ]

    @property
    def point(self) -> Point:
        return mapping(self.obj.geometry)

    @classmethod
    def _qs_for_request(cls, request):
        return BeaconMeasurement.qs_for_request(request).select_related("space", "space__level").filter(
            fill_quest=True
        )
