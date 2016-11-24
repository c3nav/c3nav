import os
from django.core.management.base import BaseCommand

from c3nav.mapdata.models import Level

svg_template = """<svg
  width="{width}"
  height="{height}"
  xmlns:svg="http://www.w3.org/2000/svg"
  xmlns="http://www.w3.org/2000/svg"
>
{data}
</svg>"""


class Command(BaseCommand):
    help = 'create svgs for each floor'

    def add_arguments(self, parser):
        parser.add_argument('folder', help='folder, where the svgs should be stored')

    def handle(self, *args, **options):
        folder = options['folder']
        os.chdir(folder)

        for level in Level.objects.all():
            level_name = "level-{}.svg".format(level.name)
            data = []
            for building in level.buildings.all():
                data.append(building.geometry.svg(fill_color="#c0c0c0"))
            for area in level.areas.all():
                data.append(area.geometry.svg(fill_color="#a0a0a0"))
            for obstacle in level.obstacles.all():
                data.append(obstacle.geometry.svg(fill_color="#ffa0a0"))
            for door in level.doors.all():
                data.append(door.geometry.svg(fill_color="#f0a0f0"))
            with open(level_name, 'w') as fh:
                fh.write(svg_template.format(width=400, height=200, data='\n'.join(data)))
