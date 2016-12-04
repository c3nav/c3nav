from django.core.management.base import BaseCommand

from c3nav.routing.graph import Graph


class Command(BaseCommand):
    help = 'build the routing graph'

    def add_arguments(self, parser):
        parser.add_argument('--draw-graph', action='store_const', const=True, default=False,
                            help='render a graph image')

        parser.add_argument('--dont-draw-graph-points', action='store_const', const=True, default=False,
                            help='dont draw points on the graph image')

        parser.add_argument('--dont-draw-graph-lines', action='store_const', const=True, default=False,
                            help='dont draw lines on the graph image')

    def handle(self, *args, **options):
        graph = Graph()
        graph.build()
        if options['draw_graph']:
            graph.draw_pngs(points=not options['dont_draw_graph_points'], lines=not options['dont_draw_graph_lines'])
