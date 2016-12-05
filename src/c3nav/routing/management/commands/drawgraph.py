from django.core.management.base import BaseCommand

from c3nav.routing.graph import Graph


class Command(BaseCommand):
    help = 'draw the routing graph'

    def add_arguments(self, parser):
        parser.add_argument('--no-points', action='store_const', dest='points', const=False, default=True,
                            help='dont draw points on the graph image')

        parser.add_argument('--no-lines', action='store_const', dest='lines', const=False, default=True,
                            help='dont draw lines on the graph image')

    def handle(self, *args, **options):
        graph = Graph.load()
        graph.draw_pngs(points=options['points'], lines=options['lines'])
