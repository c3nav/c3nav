from django.utils.translation import ugettext_lazy as _

from c3nav.mapdata.utils.cache import get_levels_cached


def main(request):
    get_levels_cached()
    _
    src = request.POST if request.method == 'POST' else request.GET
    src == 5
