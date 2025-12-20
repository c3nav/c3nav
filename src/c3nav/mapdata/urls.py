from django.urls import path, register_converter

from c3nav.mapdata.converters import (AccessPermissionsConverter, ArchiveFileExtConverter, HistoryFileExtConverter,
                                      HistoryModeConverter, SignedIntConverter, TileFileExtConverter)
from c3nav.mapdata.views import get_cache_package, map_history, preview_location, preview_route, tile
from c3nav.site.converters import LocationConverter

register_converter(LocationConverter, 'loc')
register_converter(SignedIntConverter, 'sint')
register_converter(AccessPermissionsConverter, 'a_perms')
register_converter(HistoryModeConverter, 'h_mode')
register_converter(HistoryFileExtConverter, 'h_fileext')
register_converter(TileFileExtConverter, 'img_ext')
register_converter(ArchiveFileExtConverter, 'archive_fileext')

urlpatterns = [
    path('<int:level>/<sint:zoom>/<sint:x>/<sint:y>/<int:theme>.<img_ext:ext>', tile, name='mapdata.tile'),
    path('preview/l/<loc:slug>.<img_ext:ext>', preview_location, name='mapdata.preview.location'),
    path('preview/r/<loc:slug>/<loc:slug2>.<img_ext:ext>', preview_route, name='mapdata.preview.route'),
    path('<int:level>/<sint:zoom>/<sint:x>/<sint:y>/<int:theme>/<a_perms:access_permissions>.<img_ext:ext>', tile,
         name='mapdata.tile'),
    path('history/<int:level>/<h_mode:mode>.<h_fileext:filetype>', map_history, name='mapdata.map_history'),
    path('cache/package.<archive_fileext:filetype>', get_cache_package, name='mapdata.cache_package'),
]
