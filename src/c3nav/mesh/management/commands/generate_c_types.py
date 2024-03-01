from dataclasses import fields

from django.core.management.base import BaseCommand

from c3nav.mesh.baseformats import StructType, normalize_name, StructFormat
from c3nav.mesh.messages import MeshMessage
from c3nav.mesh.utils import indent_c


class Command(BaseCommand):
    help = 'export mesh message structs for c code'

    def handle(self,  *args, **options):
        nodata = set()
        struct_lines = {}
        struct_sizes = []
        struct_max_sizes = []
        done_definitions = set()

        includes = set()
        for msg_type, msg_class in MeshMessage.get_types().items():
            # todo: run this on the union
            includes.update(StructFormat(msg_class).get_c_includes())
        for include in includes:
            print(f'#include {include}')

        ignore_names = set(field_.name for field_ in fields(MeshMessage))
        for msg_type, msg_class in MeshMessage.get_types().items():
            base_name = normalize_name(getattr(msg_type, 'name', msg_class.__name__))
            name = "mesh_msg_%s_t" % base_name

            for definition_name, definition in StructFormat(msg_class).get_c_definitions().items():
                if definition_name not in done_definitions:
                    done_definitions.add(definition_name)
                    print(definition)
                    print()

            code = StructFormat(msg_class).get_c_code(name, ignore_fields=ignore_names, no_empty=True)
            if code:
                size = StructFormat(msg_class).get_size(no_inherited_fields=True, calculate_max=False)
                max_size = StructFormat(msg_class).get_size(no_inherited_fields=True, calculate_max=True)
                struct_lines[base_name] = "%s %s;" % (name, base_name.replace('_announce', ''))
                struct_sizes.append(size)
                struct_max_sizes.append(max_size)
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
        print('#define MESH_MSG_MAX_LENGTH (%d)' % max(struct_max_sizes))

        print()

        max_msg_type = max(MeshMessage.get_types().keys())
        macro_data = []
        for i in range(((max_msg_type//16)+1)*16):
            msg_class = MeshMessage.get_types().get(i, None)
            if msg_class:
                name = normalize_name(getattr(msg_class.msg_type, 'name', msg_class.__name__))
                macro_data.append((
                    msg_class.get_c_enum_name(),
                    ("nodata" if msg_class in nodata else name),
                    StructFormat(msg_class).get_var_num(), # todo: uh?
                    StructFormat(msg_class).get_size(no_inherited_fields=True, calculate_max=True),
                    msg_class.__doc__.strip(),
                ))
            else:
                macro_data.append((
                    "RESERVED_%02X" % i,
                    "nodata",
                    0,
                    0,
                    "",
                ))

        max0 = max(len(d[0]) for d in macro_data)
        max1 = max(len(d[1]) for d in macro_data)
        max2 = max(len(str(d[2])) for d in macro_data)
        max3 = max(len(str(d[3])) for d in macro_data)
        lines = []
        for i, (macro_name, struct_name, num_len, max_len, comment) in enumerate(macro_data):
            lines.append(indent_c(
                "FN(%s %s %s %s)  /** 0x%02X %s*/" % (
                    f'{macro_name},'.ljust(max0+1),
                    f'{struct_name},'.ljust(max1+1),
                    f'{num_len},'.rjust(max2+1),
                    f'{max_len}'.rjust(max3),
                    i,
                    comment+(" " if comment else ""),
                )
            ))
        print("#define FOR_ALL_MESH_MSG_TYPES(FN)  \\")
        print("  \\\n".join(lines))
