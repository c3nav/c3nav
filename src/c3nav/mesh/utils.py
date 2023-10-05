def get_mesh_comm_group(address):
    return 'mesh_comm_%s' % address.replace(':', '-')


def indent_c(code):
    return "    "+code.replace("\n", "\n    ")


def get_node_names():
    from c3nav.mesh.models import MeshNode
    return {
        **{node.address: node.name for node in MeshNode.objects.all()},
        'ff:ff:ff:ff:ff:ff': "broadcast",
        '00:00:00:ff:ff:ff': "direct parent",
        '00:00:00:00:00:00': "root",
    }
