from django import template
from django.urls import reverse
from django.utils.html import format_html

register = template.Library()


@register.simple_tag(takes_context=True)
def mesh_node(context, bssid):
    name = context.get("node_names", {}).get(bssid, None)
    if name:
        return format_html(
            '<a href="{url}">{bssid}</a> ({name})',
            url=reverse('control.mesh.node.detail', kwargs={"pk": bssid}), bssid=bssid, name=name
        )
    else:
        return format_html(
            '<a href="{url}">{bssid}</a>',
            url=reverse('control.mesh.node.detail', kwargs={"pk": bssid}), bssid=bssid
        )
