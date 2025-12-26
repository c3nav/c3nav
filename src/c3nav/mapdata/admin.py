from c3nav.mapdata.models.geometry.space import AutoBeaconMeasurement, BeaconMeasurement
from django.contrib import admin
from django.utils.html import format_html, escape
from django.utils.safestring import mark_safe


@admin.register(AutoBeaconMeasurement)
class AutoBeaconMeasurementAdmin(admin.ModelAdmin):
    list_display = ("__str__", "datetime", "author", "ranges", "located", "suggestions")
    readonly_fields = ("located", "ranges", "data", "author", "datetime", "placed", "suggestions")
    list_filter = ("datetime", )
    search_fields = ("author__username", )
    list_per_page = 10

    def located(self, obj):
        located = obj.located_all_permissions
        location = located.location
        if location is None:
            return ""
        line = format_html('<a href="/l/{slug}/">{title}</a>', slug=located.location.slug, title=located.location.title)
        if located.precision is not None:
            line = mark_safe(str(line) + f' (+/- {located.precision:.1f} m)')
        return line

    def suggestions(self, obj):
        return mark_safe(
            "<br />".join(f"{s.bssid}, {s.frequencies}" for s in obj.located_all_permissions.suggested_peers)
        )

    def ranges(self, obj):
        return str(len([item for item in obj.data.wifi[0] if item.distance]))


@admin.register(BeaconMeasurement)
class BeaconMeasurementAdmin(admin.ModelAdmin):
    list_display = ("__str__", "actual", "located", "analysis")
    fields = ("id", "space", "data", "actual", "located", "analysis")
    readonly_fields = ("located", "actual", "analysis", "data")
    list_per_page = 10

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("space__level")
    
    def actual(self, obj):
        from c3nav.mapdata.utils.locations import CustomLocation
        from c3nav.mapdata.models import AccessRestriction
        location = CustomLocation(
            level=obj.space.level,
            x=obj.geometry.x,
            y=obj.geometry.y,
            permissions=AccessRestriction.get_all(),
            icon='my_location'
        )
        return format_html('<a href="/l/{slug}/">{title}</a>', slug=location.slug, title=location.title)

    def located(self, obj):
        result = []
        for located in obj.located_all_permissions:
            if located.location is None:
                result.append("-")
            line = format_html('<a href="/l/{slug}/">{title}</a>', slug=located.location.slug, title=located.location.title)
            if located.precision is not None:
                line = str(line) + f' (+/- {located.precision:.1f} m)'
            result.append(line)
        return mark_safe("<br>".join(result))

    def analysis(self, obj):
        result = []
        for located in obj.located_all_permissions:
            if result:
                result.append("")
            if located.analysis:
                result.extend(located.analysis)
            else:
                result.append("-")
        return mark_safe("<br>".join(result))