from typing import TYPE_CHECKING

from django.conf import settings

from c3nav.mapdata.updatejobs import register_mapupdate_job, recalculate_geometries
from c3nav.routing.locator import Locator
from c3nav.routing.router import Router

if TYPE_CHECKING:
    from c3nav.mapdata.models import MapUpdate


@register_mapupdate_job("router", dependencies=(recalculate_geometries, ))
def rebuild_router(mapupdates: tuple["MapUpdate", ...]) -> bool:
    (settings.CACHE_ROOT / mapupdates[-1].to_tuple.cache_key).mkdir(exist_ok=True)
    Router.rebuild(mapupdates[-1].to_tuple)
    return True


@register_mapupdate_job("locator", dependencies=(rebuild_router, ))
def rebuild_locator(mapupdates: tuple["MapUpdate", ...]) -> bool:
    (settings.CACHE_ROOT / mapupdates[-1].to_tuple.cache_key).mkdir(exist_ok=True)
    Locator.rebuild(mapupdates[-1].to_tuple, Router.load())
    return True