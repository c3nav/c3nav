def get_mesh_comm_group(address):
    return 'mesh_comm_%s' % address.replace(':', '-')
