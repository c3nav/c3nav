from c3nav.mapdata.models.geometry.space import AutoBeaconMeasurement
from django.contrib import admin
from django.utils.html import format_html

from c3nav.mapdata.models.access import AccessRestriction
from c3nav.routing.locator import Locator


@admin.register(AutoBeaconMeasurement)
class AutoBeaconMeasurementAdmin(admin.ModelAdmin):
    list_display = ("__str__", "datetime", "author", "ranges", "located")
    readonly_fields = ("located", "ranges", "data", "author", "datetime", "placed")
    list_filter = ("datetime", )
    search_fields = ("author__username", )
    list_per_page = 10

    def located(self, obj):
        location = Locator.load().locate(obj.data.wifi[0], permissions=AccessRestriction.get_all())
        if location is None:
            return ""
        return format_html('<a href="/l/{slug}/">{title}</a>', slug=location.slug, title=location.title)

    def ranges(self, obj):
        return str(len([item for item in obj.data.wifi[0] if item.distance]))