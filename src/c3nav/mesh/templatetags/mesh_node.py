from django import template
from django.urls import reverse
from django.utils.html import format_html

from c3nav.mesh.models import MeshNode

register = template.Library()


@register.simple_tag(takes_context=True)
def mesh_node(context, node: str | MeshNode):
    if isinstance(node, str):
        bssid = node
        name = context.get("node_names", {}).get(node, None)
    else:
        bssid = node.address
        name = node.name
    if name:
        return format_html(
            '<a href="{url}">{bssid}</a> ({name})',
            url=reverse('mesh.node.detail', kwargs={"pk": bssid}), bssid=bssid, name=name
        )
    else:
        return format_html(
            '<a href="{url}">{bssid}</a>',
            url=reverse('mesh.node.detail', kwargs={"pk": bssid}), bssid=bssid
        )


@register.filter(name="cm_to_m")
def cm_to_m(value):
    return "%.2f" % (int(value)/100)
