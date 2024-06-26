from django.core.management.base import BaseCommand

from c3nav.mesh.cformats import UnionFormat, normalize_name, CFormat
from c3nav.mesh.messages import MeshMessageContent
from c3nav.mesh.utils import indent_c


class Command(BaseCommand):
    help = 'export mesh message structs for c code'

    @staticmethod
    def get_msg_c_enum_name(msg_type):
        return normalize_name(msg_type.__name__.removeprefix('Mesh').removesuffix('Message')).upper()

    def handle(self,  *args, **options):
        nodata = set()
        struct_lines = {}
        struct_sizes = []
        struct_max_sizes = []
        done_definitions = set()

        mesh_msg_content_format = CFormat.from_annotation(MeshMessageContent)
        if not isinstance(mesh_msg_content_format, UnionFormat):
            raise Exception('wuah')
        discriminator_size = mesh_msg_content_format.discriminator_format.get_size()
        for include in mesh_msg_content_format.get_c_includes():
            print(f'#include {include}')

        for msg_type, msg_content_format in mesh_msg_content_format.models.items():
            base_name = normalize_name(mesh_msg_content_format.key_to_name[msg_type])
            name = "mesh_msg_%s_t" % base_name

            for definition_name, definition in msg_content_format.get_c_definitions().items():
                if definition_name not in done_definitions:
                    done_definitions.add(definition_name)
                    print(definition)
                    print()

            code = msg_content_format.get_c_code(name, ignore_fields=('msg_type', ), no_empty=True)
            if code:
                size = msg_content_format.get_size(calculate_max=False)
                max_size = msg_content_format.get_size(calculate_max=True)
                size -= discriminator_size
                max_size -= discriminator_size
                struct_lines[base_name] = "%s %s;" % (name, base_name.replace('_announce', ''))
                struct_sizes.append(size)
                struct_max_sizes.append(max_size)
                print(code)
                print("static_assert(sizeof(%s) == %d, \"size of generated message structs is calculated wrong\");" %
                      (name, size))
                print()
            else:
                nodata.add(msg_content_format.model)

        print("/** union between all message data structs */")
        print("typedef union __packed {")
        for line in struct_lines.values():
            print(indent_c(line))
        print("} mesh_msg_data_t;")
        print(
            "static_assert(sizeof(mesh_msg_data_t) == %d, \"size of generated message structs is calculated wrong\");"
            % max(struct_sizes)
        )

        print()
        print('#define MESH_MSG_MAX_LENGTH (%d)' % max(struct_max_sizes))

        print()

        max_msg_type = max(mesh_msg_content_format.models.keys())
        macro_data = []
        for i in range(((max_msg_type//16)+1)*16):
            msg_content_format = mesh_msg_content_format.models.get(i, None)
            if msg_content_format:
                name = normalize_name(mesh_msg_content_format.key_to_name[i])
                macro_data.append((
                    self.get_msg_c_enum_name(msg_content_format.model),
                    ("nodata" if msg_content_format.model in nodata else name),
                    msg_content_format.get_var_num(), # todo: uh?
                    msg_content_format.get_size(calculate_max=True) - discriminator_size,
                    msg_content_format.model.__doc__.strip(),
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
