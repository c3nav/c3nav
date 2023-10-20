from dataclasses import fields

from django.core.management.base import BaseCommand

from c3nav.mesh.baseformats import normalize_name
from c3nav.mesh.messages import MeshMessage
from c3nav.mesh.utils import indent_c


class Command(BaseCommand):
    help = 'export mesh message structs for c code'

    def handle(self,  *args, **options):
        done_struct_names = set()
        nodata = set()
        struct_lines = {}
        struct_sizes = []
        done_definitions = set()

        ignore_names = set(field_.name for field_ in fields(MeshMessage))
        for msg_type, msg_class in MeshMessage.get_types().items():
            if msg_class.c_struct_name:
                if msg_class.c_struct_name in done_struct_names:
                    continue
                done_struct_names.add(msg_class.c_struct_name)
                msg_class = MeshMessage.c_structs[msg_class.c_struct_name]

            base_name = (msg_class.c_struct_name or normalize_name(
                getattr(msg_type, 'name', msg_class.__name__)
            ))
            name = "mesh_msg_%s_t" % base_name

            for definition_name, definition in msg_class.get_c_definitions().items():
                if definition_name not in done_definitions:
                    done_definitions.add(definition_name)
                    print(definition)
                    print()

            code = msg_class.get_c_code(name, ignore_fields=ignore_names, no_empty=True)
            if code:
                size = msg_class.get_min_size(no_inherited_fields=True)
                struct_lines[base_name] = "%s %s;" % (name, base_name.replace('_announce', ''))
                struct_sizes.append(size)
                print(code)
                print("static_assert(sizeof(%s) == %d, \"size of generated message structs is calculated wrong\");" %
                      (name, size))
                print()
            else:
                nodata.add(msg_class)

        print("/** union between all message data structs */")
        print("typedef union __packed {")
        for line in struct_lines.values():
            print(indent_c(line))
        print("} mesh_msg_data_t; ")
        print(
            "static_assert(sizeof(mesh_msg_data_t) == %d, \"size of generated message structs is calculated wrong\");"
            % max(struct_sizes)
        )

        print()

        max_msg_type = max(MeshMessage.get_types().keys())
        macro_data = []
        for i in range(((max_msg_type//16)+1)*16):
            msg_class = MeshMessage.get_types().get(i, None)
            if msg_class:
                name = (msg_class.c_struct_name or normalize_name(
                    getattr(msg_class.msg_type, 'name', msg_class.__name__)
                ))
                macro_data.append((
                    msg_class.get_c_enum_name()+',',
                    ("nodata" if msg_class in nodata else name)+',',
                    msg_class.get_var_num(),
                    msg_class.__doc__.strip(),
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
