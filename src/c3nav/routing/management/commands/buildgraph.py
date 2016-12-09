import time

from django.core.management.base import BaseCommand

from c3nav.routing.graph import Graph


class Command(BaseCommand):
    help = 'build the routing graph'

    def handle(self, *args, **options):
        start = time.time()
        graph = Graph()
        graph.build()
        print()
        print('Built in %.4fs' % (time.time() - start))

        start = time.time()
        graph.save()
        print('Saved in %.4fs' % (time.time()-start))

        start = time.time()
        Graph.load()
        print('Loaded in %.4fs' % (time.time() - start))
