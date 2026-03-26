import re
from collections import deque, defaultdict
from html import escape
from pathlib import Path

from django.contrib.staticfiles import finders
from django.test.client import Client

from c3nav.mapdata.models.locations import LocationSlug, LocationRedirect


def clean_html(html: str) -> str:
    user_data = '{"logged_in":false,"allow_editor":false,"allow_control_panel":false,"mesh_control":false,"has_positions":false,"title":"Archive","subtitle":null,"permissions":[],"overlays":[],"quests":{}}'
    html = re.sub(r'<meta property="[a-z]+:url" content="[^"]+"/>', '', html)
    html = re.sub(r'<meta property="[a-z]+:url" content="[^"]+"/>', '', html)
    html = re.sub(r'data-ssids="[^"]+"', '', html)
    html = re.sub(r'data-user-data="[^"]+"', 'data-user-data="'+escape(user_data)+'"', html)
    html = re.sub(r'<a class="[^"]*(report|editor).*?</a>', '', html, flags=re.DOTALL)
    html = re.sub(r'<button class="[^"]*route.*?</button>', '', html, flags=re.DOTALL)

    html = html.replace('<head>', '<head><meta charset="utf-8" /> ')
    html = html.replace('<img src="">', '')
    return html


def static_archive(output_dir: Path, permissions: set[int], redirects: dict[Path, Path], png: bool = False):
    c = Client()
    response = c.get("/")
    with (output_dir / "index.html").open("w") as f:
        f.write(clean_html(response.content.decode()))

    staticfiles_found = {
        *(Path(m[1]) for m in re.findall(r'(src|href)="(/static/[^"]+)"', response.content.decode())),
        Path("/static") / "img" / "marker-icon-default.png",
        Path("/static") / "img" / "marker-icon-origin.png",
        Path("/static") / "img" / "marker-icon-destination.png",
        Path("/static") / "img" / "marker-icon-nearby.png",
        Path("/static") / "img" / "marker-icon-default-2x.png",
        Path("/static") / "img" / "marker-icon-origin-2x.png",
        Path("/static") / "img" / "marker-icon-destination-2x.png",
        Path("/static") / "img" / "marker-icon-nearby-2x.png",
        Path("/static") / "img" / "marker-shadow.png",
    }
    staticfiles_left = deque(staticfiles_found)
    while staticfiles_left:
        staticfile = staticfiles_left.popleft()

        static_dest = output_dir / staticfile.relative_to("/")
        static_dest.parent.mkdir(parents=True, exist_ok=True)

        result = finders.find(str(staticfile).removeprefix("/static/"))
        if result is None:
            print(f"couldn't find: {staticfile}")
            continue
        with Path(result).open("rb") as f:
            content = f.read()

        if staticfile.suffix == ".css":
            staticfiles_new = {
                staticfile.parent / Path(match) for match in
                re.findall(r'url\(["\']?([^\'"\(\)]+)["\']?\)', content.decode())
            } - staticfiles_found
            if staticfiles_new:
                staticfiles_found.update(staticfiles_new)
                staticfiles_left.extend(staticfiles_new)

        with static_dest.open("wb") as f:
            print(static_dest)
            f.write(content)

    # auth API
    api_out = output_dir / "api" / "v2"

    auth_api_out = api_out / "auth" / "session" / "index.html"
    auth_api_out.parent.mkdir(parents=True, exist_ok=True)
    with auth_api_out.open("w") as f:
        print(auth_api_out)
        f.write('{"key": "staticarchive"}')

    # locations
    print(f"downloading all locations...")

    redirects_to_id = defaultdict(list)
    for slug, target_id in LocationRedirect.objects.values_list("slug", "target_id"):
        redirects_to_id[target_id].append(slug)

    for location in LocationSlug.objects.filter():
        location = location.get_child()
        if getattr(location, "can_search", False) and location.access_restriction_id is None:
            redirectslugs = redirects_to_id.get(location.id, [])
            if location.slug:
                redirectslugs.append(f"{LocationSlug.LOCATION_TYPE_CODES[location.__class__.__name__]}:{location.id}")

            for slug in redirectslugs:
                redirects[Path("l") / slug] = Path("l") / location.effective_slug

            path = Path("l") / location.effective_slug
            response = c.get(f"/{path}/")
            if response.status_code != 200:
                continue
            output_path = output_dir / path / "index.html"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w") as f:
                f.write(clean_html(response.content.decode()))
