from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from shapely import Point
from shapely.geometry import mapping

from c3nav.mapdata.models.geometry.space import RangingBeacon
from c3nav.mapdata.quests.base import ChangeSetModelForm, register_quest, Quest


class RangingBeaconAltitudeQuestForm(ChangeSetModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["altitude"].label = (
            _('How many meters above ground is the access point “%s” mounted?') % self.instance.comment
        )

    def clean_altitude(self):
        data = self.cleaned_data["altitude"]
        if not data:
            raise ValidationError(_("The AP should not be 0m above ground."))
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
