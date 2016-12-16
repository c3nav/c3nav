import time

from django.core.management.base import BaseCommand

from c3nav.routing.graph import Graph


class Command(BaseCommand):
    help = 'check how long it takes to build the routers for the routing graph'

    def handle(self, *args, **options):
        start = time.time()
        graph = Graph.load()
        print('Graph loaded in %.4fs' % (time.time() - start))

        start = time.time()
        graph.build_routers()
        print('Routers built in %.4fs' % (time.time() - start))

        start = time.time()
        graph.build_routers()
        print('Routers built (2nd time, cached) in %.4fs' % (time.time() - start))
