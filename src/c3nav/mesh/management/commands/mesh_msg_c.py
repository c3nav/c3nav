from dataclasses import fields

from django.core.management.base import BaseCommand

from c3nav.mesh.dataformats import normalize_name
from c3nav.mesh.messages import MeshMessage
from c3nav.mesh.utils import indent_c


class Command(BaseCommand):
    help = 'export mesh message structs for c code'

    def handle(self, *args, **options):
        done_struct_names = set()
        nodata = set()
        struct_lines = {}

        ignore_names = set(field_.name for field_ in fields(MeshMessage))
        from pprint import pprint
        pprint(MeshMessage.get_msg_types())
        for msg_id, msg_type in MeshMessage.get_msg_types().items():
            if msg_type.c_struct_name:
                if msg_type.c_struct_name in done_struct_names:
                    continue
                done_struct_names.add(msg_type.c_struct_name)
                msg_type = MeshMessage.c_structs[msg_type.c_struct_name]

            name = "mesh_msg_%s_t" % (
                msg_type.c_struct_name or normalize_name(getattr(msg_id, 'name', msg_type.__name__))
            )
            code = msg_type.get_c_code(name, ignore_fields=ignore_names, no_empty=True)
            if code:
                print(code)
                print()
            else:
                nodata.add(msg_type)
        return
        print("/** union between all message data structs */")
        print("typedef union __packed {")
        for line in struct_lines.values():
            print(indent_c(line))
        print("} mesh_msg_data_t;")
        print()

        max_msg_type = max(MeshMessage.msg_types.keys())
        macro_data = []
        for i in range(((max_msg_type//16)+1)*16):
            msg_type = MeshMessage.msg_types.get(i, None)
            if msg_type:
                macro_data.append((
                    msg_type.get_c_enum_name()+',',
                    ("nodata" if msg_type in nodata else msg_type.get_c_struct_name())+',',
                    msg_type.get_var_num(),
                    msg_type.__doc__.strip(),
                ))
            else:
                macro_data.append((
                    "RESERVED_%02X," % i,
                    "nodata,",
                    0,
                    "",
                ))

        max0 = max(len(d[0]) for d in macro_data)
        max1 = max(len(d[1]) for d in macro_data)
        max2 = max(len(str(d[2])) for d in macro_data)
        lines = []
        for i, (macro_name, struct_name, num_len, comment) in enumerate(macro_data):
            lines.append(indent_c(
                "FN(%s %s %s)  /** 0x%02X %s*/" % (
                    macro_name.ljust(max0),
                    struct_name.ljust(max1),
                    str(num_len).rjust(max2),
                    i,
                    comment+(" " if comment else ""),
                )
            ))
        print("#define FOR_ALL_MESH_MSG_TYPES(FN)  \\")
        print("  \\\n".join(lines))
