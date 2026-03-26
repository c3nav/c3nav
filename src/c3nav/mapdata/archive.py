import bisect
import concurrent
import json
import random
import time
from collections import defaultdict
from itertools import chain
from pathlib import Path
from typing import Iterable
from c3nav.mapdata.render.engines import ImageRenderEngine

from django.test.client import Client

from c3nav.mapdata.models import Theme, Source, Level, LocationSlug
from c3nav.mapdata.models.locations import LocationRedirect
from c3nav.mapdata.render.theme import ColorManager
from c3nav.mapdata.utils.tiles import (get_tile_bounds)


def static_archive(output_dir: Path, permissions: set[int], redirects: dict[Path, Path], png: bool = False):
    # mapdata API
    api_base = Path("api") / "v2"

    c = Client()

    def archive_api(api_path: Path, suffix: str = ""):
        response = c.get(f"/{api_path}/{suffix}", headers={"X-API-Key": "anonymous"}, follow=True)
        api_out = output_dir / api_path / "index.html"
        api_out.parent.mkdir(parents=True, exist_ok=True)
        with api_out.open("wb") as f:
            f.write(response.content)
        return response.content

    # general map stuff
    print("downloading base map API endpoints...")
    archive_api(api_base / "map" / "bounds")
    archive_api(api_base / "map" / "settings")
    for theme_id in chain((0, ), Theme.objects.values_list("id", flat=True)):
        archive_api(api_base / "map" / "legend" / str(theme_id))

    # location API
    archive_api(api_base / "map" / "locations", "?searchable=true")
    locations = json.loads(archive_api(api_base / "map" / "locations" / "full"))
    random.shuffle(locations)

    # download all locations

    print(f"downloading all locations...")
    redirects_to_id = defaultdict(list)
    for slug, target_id in LocationRedirect.objects.values_list("slug", "target_id"):
        redirects_to_id[target_id].append(slug)

    def generate_location_paths():
        for location in LocationSlug.objects.filter(pk__in=[location["id"] for location in locations]):
            location = location.get_child()
            redirectslugs = redirects_to_id.get(location.id, [])
            if location.slug:
                redirectslugs.append(f"{LocationSlug.LOCATION_TYPE_CODES[location.__class__.__name__]}:{location.id}")

            for slug in redirectslugs:
                redirects.update(dict(zip(
                    (
                        api_base / "map" / "locations" / "by-slug" / slug,
                        api_base / "map" / "locations" / "by-slug" / slug / "full",
                        api_base / "map" / "locations" / "by-slug" / slug / "geometry",
                        api_base / "map" / "locations" / "by-slug" / slug / "display",
                    ),
                    (
                        api_base / "map" / "locations" / "by-slug" / location.effective_slug,
                        api_base / "map" / "locations" / "by-slug" / location.effective_slug / "full",
                        api_base / "map" / "locations" / "by-slug" / location.effective_slug / "geometry",
                        api_base / "map" / "locations" / "by-slug" / location.effective_slug / "display",
                    ),
                )))

            yield [
                api_base / "map" / "locations" / str(location.id),
                api_base / "map" / "locations" / str(location.id) / "full",
                api_base / "map" / "locations" / str(location.id) / "geometry",
                api_base / "map" / "locations" / str(location.id) / "display",
                api_base / "map" / "locations" / "by-slug" / location.effective_slug,
                api_base / "map" / "locations" / "by-slug" / location.effective_slug / "full",
                api_base / "map" / "locations" / "by-slug" / location.effective_slug / "geometry",
                api_base / "map" / "locations" / "by-slug" / location.effective_slug / "display",
            ]

    def download_location(api_paths: Iterable[Path]):
        for api_path in api_paths:
            archive_api(api_path)

    start_time = time.time()
    next_msg = 0
    erase = 0
    done_locations = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        for future in executor.map(download_location, generate_location_paths(), buffersize=32):
            done_locations += 1

            now = time.time()
            if now > next_msg:
                next_msg = now + 0.5
                time_to_go = int((now - start_time) / done_locations * (len(locations) - done_locations))
                msg = (f"...{done_locations / len(locations) * 100:.1f}% complete ({done_locations}/{len(locations)}) - "
                       f"{time_to_go // 60:02d}m{time_to_go % 60:02d}s remaining").ljust(erase, " ")
                print(("\b" * erase) + msg, end="")
                erase = len(msg)

    msg = f"...100.0% complete ({len(locations)}/{len(locations)})"
    print(("\b" * erase) + msg)

    # previews
    static_archive_previews(c, output_dir, locations=[l["id"] for l in locations], png=png)

    # tiles
    static_archive_tiles(c, output_dir)


def static_archive_previews(c: Client, output_dir: Path, locations: Iterable[int], png: bool = False):
    locations = [location for location in
                 (location.get_child() for location in LocationSlug.objects.filter(pk__in=locations))
                 if getattr(location, "can_search", False)]
    preview_variants = (2 if png else 1)
    num_previews = len(locations) * preview_variants

    print(f"archiving previews...")

    def generate_preview_paths():
        for location in locations:
            if png:
                yield Path("map") / "preview" / "l" / f"{location.effective_slug}.png"
            yield Path("map") / "preview" / "l" / f"{location.effective_slug}.webp"

    def download_previews(preview_path: Path):
        response = c.get(f"/{preview_path}")
        if response.status_code != 200:
            return
        preview_out = output_dir / preview_path
        preview_out.parent.mkdir(parents=True, exist_ok=True)
        with preview_out.open("wb") as f:
            f.write(response.content)

    start_time = time.time()
    next_msg = 0
    erase = 0
    done_previews = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        for future in executor.map(download_previews, generate_preview_paths(), buffersize=32):
            done_previews += 1

            now = time.time()
            if now > next_msg:
                next_msg = now + 0.5
                time_to_go = int((now - start_time) / done_previews * (num_previews - done_previews))
                msg = (f"...{done_previews / num_previews * 100:.1f}% complete ({done_previews}/{num_previews}) - "
                       f"{time_to_go // 60:02d}m{time_to_go % 60:02d}s remaining").ljust(erase, " ")
                print(("\b" * erase) + msg, end="")
                erase = len(msg)

    msg = f"...100.0% complete ({num_previews}/{num_previews})"
    print(("\b" * erase) + msg)


def static_archive_tiles(c: Client, output_dir: Path):
    for zoom in range(-2, 5+1):
        static_archive_tiles_at_zoom(c, output_dir, zoom)


def static_archive_tiles_at_zoom(c: Client, output_dir: Path, zoom: int, png: bool = False):
    (source_minx, source_miny), (source_maxx, source_maxy) = Source.max_bounds()

    # todo: this could be done better but oh well
    final_min_x = 0
    minx, miny, maxx, maxy = get_tile_bounds(zoom, final_min_x, 0)
    if maxx < source_minx:
        while maxx <= source_minx:
            final_min_x += 1
            minx, miny, maxx, maxy = get_tile_bounds(zoom, final_min_x, 0)
    else:
        while minx >= source_minx:
            final_min_x -= 1
            minx, miny, maxx, maxy = get_tile_bounds(zoom, final_min_x, 0)

    final_max_y = 0
    minx, miny, maxx, maxy = get_tile_bounds(zoom, 0, final_max_y)
    if maxy < source_miny:
        while maxy < source_miny:
            final_max_y -= 1
            minx, miny, maxx, maxy = get_tile_bounds(zoom, 0, final_max_y)
    else:
        while miny >= source_miny:
            final_max_y += 1
            minx, miny, maxx, maxy = get_tile_bounds(zoom, 0, final_max_y)
        final_max_y -= 1

    final_max_x = final_min_x
    minx, miny, maxx, maxy = get_tile_bounds(zoom, final_max_x, 0)
    while minx < source_maxx:
        final_max_x += 1
        minx, miny, maxx, maxy = get_tile_bounds(zoom, final_max_x, 0)
    final_max_x -= 1

    final_min_y = final_max_y
    minx, miny, maxx, maxy = get_tile_bounds(zoom, 0, final_min_y)
    while miny < source_maxy:
        final_min_y -= 1
        minx, miny, maxx, maxy = get_tile_bounds(zoom, 0, final_min_y)
    final_min_y += 1

    # calculate how many tiles need to be downloaded
    level_ids = list(Level.objects.filter(access_restriction_id=None,
                                          on_top_of_id__isnull=True).values_list("id", flat=True))
    theme_ids = [0] + list(Theme.objects.values_list("id", flat=True))
    num_x = (final_max_x - final_min_x) + 1
    num_y = (final_max_y - final_min_y) + 1
    tile_variants = len(level_ids) * len(theme_ids) * (2 if png else 1)
    num_tiles = num_x * num_y * tile_variants

    theme_blanks = {}

    for theme_id in theme_ids:
        tile_out_dir = output_dir / "map" / "blank"
        tile_out_dir.mkdir(parents=True, exist_ok=True)

        content = ImageRenderEngine(
            width=257, height=257, background=ColorManager.for_theme(theme_id or None).background
        ).render()
        theme_blanks[theme_id] = content

        if png:
            with (tile_out_dir / f"{theme_id}.png").open("wb") as f:
                f.write(content[0])

        with (tile_out_dir / f"{theme_id}.webp").open("wb") as f:
            f.write(content[1])


    print(f"archiving tiles at zoom={zoom} {final_min_x}<=x<={final_max_x} {final_min_y}<=y<={final_max_y}")

    def generate_tile_paths():
        allxy = list(range(num_x * num_y))
        while allxy:
            xy = random.choice(allxy)
            allxy.pop(bisect.bisect_left(allxy, xy))
            y = final_min_y + (xy // num_x)
            x = final_min_x + (xy % num_x)
            for level_id in level_ids:
                for theme_id in theme_ids:
                    if png:
                        yield Path("map") / str(level_id) / str(zoom) / str(x) / str(y) / f"{theme_id}.png"
                    yield Path("map") / str(level_id) / str(zoom) / str(x) / str(y) / f"{theme_id}.webp"

    def download_tile(tile_path: Path):
        response = c.get(f"/{tile_path}")
        if response.content != theme_blanks[int(tile_path.name.split('.')[0])][int(tile_path.suffix == '.webp')]:
            tile_out = output_dir / tile_path
            tile_out.parent.mkdir(parents=True, exist_ok=True)
            with tile_out.open("wb") as f:
                f.write(response.content)

    start_time = time.time()
    next_msg = 0
    erase = 0
    done_tiles = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        for future in executor.map(download_tile, generate_tile_paths(), buffersize=32):
            done_tiles += 1

            now = time.time()
            if now > next_msg:
                next_msg = now + 0.5
                time_to_go = int((now - start_time) / done_tiles * (num_tiles - done_tiles))
                msg = (f"...{done_tiles / num_tiles * 100:.1f}% complete ({done_tiles}/{num_tiles}) - "
                       f"{time_to_go // 60:02d}m{time_to_go % 60:02d}s remaining").ljust(erase, " ")
                print(("\b" * erase) + msg, end="")
                erase = len(msg)

    msg = f"...100.0% complete ({num_tiles}/{num_tiles})"
    print(("\b" * erase) + msg)








