from collections import namedtuple
from operator import attrgetter

from c3nav.mapdata.models.geometry.space import RangingBeacon


def get_mesh_uplink_group(address):
    return 'mesh_uplink_%s' % address.replace(':', '-')


MESH_ALL_UPLINKS_GROUP = "mesh_uplink_all"
MESH_ALL_OTA_GROUP = "mesh_ota_all"
UPLINK_PING = 5
UPLINK_TIMEOUT = UPLINK_PING+5


def indent_c(code):
    return "    "+code.replace("\n", "\n    ").replace("\n    \n", "\n\n")


def get_node_names():
    from c3nav.mesh.models import MeshNode
    from c3nav.mesh.messages import MeshMessageType
    return {
        **{node.address: node.name for node in MeshNode.objects.prefetch_last_messages(MeshMessageType.CONFIG_NODE)},
        'ff:ff:ff:ff:ff:ff': "broadcast",
        '00:00:00:ff:ff:ff': "direct parent",
        '00:00:00:00:00:00': "root",
    }


def group_msg_type_choices(msg_types):
    msg_types = sorted(msg_types, key=attrgetter('value'))
    choices = {}
    for msg_type in msg_types:
        choices.setdefault(msg_type.name.split('_')[0].lower(), []).append(
            (msg_type.name, msg_type.pretty_name)
        )
    return tuple(choices.items())


NodesAndBeacons = namedtuple("NodesAndBeacons", ("beacons", "nodes", "nodes_for_beacons"))


def get_nodes_and_ranging_beacons():
    from c3nav.mesh.models import MeshNode
    beacons = {beacon.id: beacon for beacon in RangingBeacon.objects.all().select_related("space")}
    nodes = {
        node.address: node
        for node in MeshNode.objects.all().prefetch_last_messages().prefetch_ranging_beacon()
    }
    nodes_for_beacons = {
        node.ranging_beacon.id: node
        for node in nodes.values()
        if node.ranging_beacon and node.ranging_beacon.id in beacons
    }
    return NodesAndBeacons(
        beacons=beacons,
        nodes=nodes,
        nodes_for_beacons=nodes_for_beacons
    )
