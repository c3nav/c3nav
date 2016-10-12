import difflib
import json
import os
import sys
from datetime import datetime

from django.conf import settings
from django.utils import timezone

from c3nav.mapdata.models import Package
from c3nav.mapdata.packageio.const import ordered_models
from c3nav.mapdata.utils import json_encoder_reindent


class MapdataWriter:
    def __init__(self):
        self.keep = set()
        self.write = []
        self.delete = []

    def prepare_write_packages(self, prettify=False, diff=False):
        print('Writing Map Packages…')

        count = 0
        for model in ordered_models:
            for obj in model.objects.all().order_by('name').prefetch_related():
                file_path = os.path.join(obj.package.directory, obj.get_filename())
                full_file_path = os.path.join(settings.MAP_ROOT, file_path)
                self.keep.add(file_path)

                new_data = obj.tofile()
                new_data_encoded = json_encode(new_data)
                old_data = None
                old_data_encoded = None

                if os.path.isfile(full_file_path):
                    with open(full_file_path) as f:
                        old_data_encoded = f.read()
                    old_data = json.loads(old_data_encoded, parse_int=float)

                    if old_data != json.loads(new_data_encoded, parse_int=float):
                        if not diff:
                            print('- Updated: ' + file_path)
                    elif old_data_encoded != new_data_encoded:
                        if not prettify:
                            continue
                        if not diff:
                            print('- Prettified: ' + file_path)
                    else:
                        continue
                else:
                    if not diff:
                        print('- Created: ' + file_path)

                if diff:
                    sys.stdout.writelines(difflib.unified_diff(
                        [] if old_data is None else [(line + '\n') for line in old_data_encoded.split('\n')],
                        [(line + '\n') for line in new_data_encoded.split('\n')],
                        fromfiledate=timezone.make_aware(
                            datetime.fromtimestamp(0 if old_data is None else os.path.getmtime(full_file_path))
                        ).isoformat(),
                        tofiledate=timezone.now().isoformat(),
                        fromfile=file_path,
                        tofile=file_path
                    ))
                    print()

                self.write.append((file_path, new_data_encoded))
                count += 1

        # Delete old files
        for package_dir in Package.objects.all().values_list('directory', flat=True):
            for path, sub_dirs, filenames in os.walk(os.path.join(settings.MAP_ROOT, package_dir)):
                sub_dirs[:] = sorted([directory for directory in sub_dirs if not directory.startswith('.')])
                for filename in sorted(filenames):
                    if not filename.endswith('.json'):
                        continue
                    file_path = os.path.join(path[len(settings.MAP_ROOT) + 1:], filename)
                    if file_path not in self.keep:
                        if not diff:
                            print('- Deleted: ' + file_path)
                        else:
                            full_file_path = os.path.join(path, filename)
                            lines = list(open(full_file_path).readlines())
                            if not lines:
                                lines = ['\n']
                            sys.stdout.writelines(difflib.unified_diff(
                                lines,
                                [],
                                fromfiledate=timezone.make_aware(
                                    datetime.fromtimestamp(os.path.getmtime(full_file_path))
                                ).isoformat(),
                                tofiledate=timezone.make_aware(
                                    datetime.fromtimestamp(0)
                                ).isoformat(),
                                fromfile=file_path,
                                tofile=file_path
                            ))
                            print()
                        self.delete.append(file_path)

        return count

    def do_write_packages(self):
        for file_path, content in self.write:
            full_file_path = os.path.join(settings.MAP_ROOT, file_path)
            try:
                os.makedirs(os.path.split(full_file_path)[0])
            except os.error:
                pass
            if content is not None:
                with open(full_file_path, 'w') as f:
                    f.write(content)

        for file_path in self.delete:
            full_file_path = os.path.join(settings.MAP_ROOT, file_path)
            os.remove(full_file_path)


def json_encode(data):
    return json_encoder_reindent(json.dumps, data, indent=4)+'\n'
