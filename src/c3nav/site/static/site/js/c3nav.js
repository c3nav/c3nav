(function () {
    /*
     * Workaround for 1px lines appearing in some browsers due to fractional transforms
     * and resulting anti-aliasing.
     * https://github.com/Leaflet/Leaflet/issues/3575
     */
    // TODO: commented out for now since the new css seems to fix it in firefox and chrome
    //       need to check on current phone browsers before removing
    // var originalInitTile = L.GridLayer.prototype._initTile;
    // L.GridLayer.include({
    //     _initTile: function (tile) {
    //         originalInitTile.call(this, tile);
    //
    //         var tileSize = this.getTileSize();
    //
    //         tile.style.width = tileSize.x + 1 + 'px';
    //         tile.style.height = tileSize.y + 1 + 'px';
    //     }
    // });

    /*
     * Fix scroll wheel zoom on precise scrolling devices
     */
    var originalPerformZoom = L.Map.ScrollWheelZoom.prototype._performZoom;
    L.Map.ScrollWheelZoom.include({
        _performZoom: function () {
            if (this._delta) this._delta = (this._delta > 0) ? Math.max(this._delta, 60) : Math.min(this._delta, -60);
            originalPerformZoom.call(this);
        }
    });

    /*
     * Polyfill for Math.Log2 because Internet Explorer sucks
     */
    // TODO: I think we can remove internet explorer polyfills at this point
    Math.log2 = Math.log2 || function (x) {
        return Math.log(x) * Math.LOG2E;
    };

    var originalGetIconBox = L.LayerGroup.Collision.prototype._getIconBox;
    L.LayerGroup.Collision.prototype._getIconBox = function (el) {
        var result = originalGetIconBox(el);
        var offsetX = (result[2] - result[0] / 2),
            offsetY = (result[3] - result[1] / 2);
        result[0] -= offsetX;
        result[1] -= offsetY;
        result[2] -= offsetX;
        result[3] -= offsetY;
        return result
    };
}());


c3nav = {
    request: async function (resource, options) {
        if (!options) {
            options = {};
        }
        const res = await fetch(resource, {
            ...options,
            headers: {
                ...options.headers,
                'X-CSRFToken': c3nav.get_csrf_token(),
            },
        });
        if (res.ok) {
            return res;
        } else {
            throw new Error(res.statusText);
        }
    },
    json_get: function (resource) {
        return c3nav.request(resource, {
            headers: {
                'Accept': 'application/json'
            }
        }).then(res => res.json());
    },
    json_post: function (resource, data) {
        return c3nav.request(resource, {
            body: JSON.stringify(data),
            method: 'POST',
            headers: {
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            }
        }).then(res => res.json());
    },


    settings: null,
    init_completed: false,
    user_data: null,
    sidebar: null,
    modal: null,
    messages: null,
    init: function () {
        c3nav.settings = new Settings(localStorage);
        c3nav.sidebar = new Sidebar(document.querySelector('#sidebar'));
        c3nav.modal = new Modal(document.querySelector('#modal'));
        c3nav.messages = new Messages(document.querySelector('#messages'));

        c3nav.load_material_icons_if_needed();
        c3nav.load_searchable_locations();


        const appAds = document.querySelector('.app-ads');
        if (!window.mobileclient && !c3nav.settings.get('hideAppAds', false) && navigator.userAgent.toLowerCase().indexOf("android") > -1) {
            appAds.classList.remove('hidden');

            on(appAds, 'click', '.close', e => {
                c3nav.settings.set('hideAppAds', true);
                appAds.remove();
            })
        } else {
            appAds.remove();
        }

        if (window.mobileclient) {
            document.body.classList.add('mobileclient');
            c3nav._set_user_location(null);
        } else {
            document.addEventListener('visibilitychange', c3nav.on_visibility_change, false);
        }

        if (document.body.dataset.hasOwnProperty('userData')) {
            c3nav._set_user_data(JSON.parse(document.body.dataset.userData));
        }
    },
    _searchable_locations_timer: null,
    load_searchable_locations: function () {
        c3nav._searchable_locations_timer = null;
        $.ajax({
            dataType: "json",
            url: '/api/locations/?searchable',
            success: c3nav._searchable_locations_loaded,
            ifModified: true,
        }).fail(function () {
            if (c3nav._searchable_locations_timer === null) {
                c3nav._searchable_locations_timer = window.setTimeout(c3nav.load_searchable_locations, c3nav.init_completed ? 300000 : 15000);
            }
        });
    },
    _sort_labels: function (a, b) {
        var result = (a[0].label_settings.min_zoom || -10) - (b[0].label_settings.min_zoom || -10);
        if (result === 0) result = b[0].label_settings.font_size - a[0].label_settings.font_size;
        return result;
    },
    _last_time_searchable_locations_loaded: null,
    _searchable_locations_interval: 120000,
    _searchable_locations_loaded: function (data) {
        c3nav._last_time_searchable_locations_loaded = Date.now();
        if (data !== undefined) {
            var locations = [],
                locations_by_id = {},
                labels = {};
            for (var i = 0; i < data.length; i++) {
                var location = data[i];
                location.title_words = location.title.toLowerCase().split(/\s+/);
                location.subtitle_words = location.subtitle.toLowerCase().split(/\s+/);
                location.match = ' ' + location.title_words.join(' ') + ' ' + location.subtitle_words.join(' ') + '  ' + location.slug + ' ' + location.add_search.toLowerCase();
                locations.push(location);
                locations_by_id[location.id] = location;
                if (location.point && location.label_settings) {
                    if (!(location.point[0] in labels)) labels[location.point[0]] = [];
                    labels[location.point[0]].push([location, c3nav._build_location_label(location)]);
                }
            }
            for (level_id in labels) {
                labels[level_id].sort(c3nav._sort_labels);
            }
            c3nav.locations = locations;
            c3nav.locations_by_id = locations_by_id;
            c3nav.labels = labels;
        } else {
            // 304, nothing to do!
        }
        if (!c3nav.init_completed) {
            c3nav.continue_init();
        }
        if (c3nav._searchable_locations_timer === null) {
            c3nav._searchable_locations_timer = window.setTimeout(c3nav.load_searchable_locations, c3nav._searchable_locations_interval);
        }
    },
    ssids: null,
    random_location_groups: null,
    continue_init: function () {
        c3nav.init_map();

        const $main = document.querySelector('main');

        const state = JSON.parse($main.dataset.state);
        c3nav.embed = $main.matches('[data-embed]');

        c3nav.last_site_update = JSON.parse($main.dataset.lastSiteUpdate);
        c3nav.new_site_update = false;

        c3nav._primary_color = $main.dataset.primaryColor || L.polyline([0, 0]).options.color;

        if ($main.dataset.hasOwnProperty('ssids')) {
            c3nav.ssids = JSON.parse($main.dataset.ssids);
        }

        if ($main.dataset.hasOwnProperty('randomLocationGroups')) {
            c3nav.random_location_groups = $main.dataset.randomLocationGroups.split(',').map(id => parseInt(id));
        }

        history.replaceState(state, window.location.path);
        c3nav.load_state(state, true);
        c3nav.update_map_locations();
        c3nav._push_state(state, true);
        if (!state.center) {
            if (state.routing && state.origin && state.destination) {
                // do nothing, we will fly after loading the route result
            } else if (state.origin || state.destination) {
                c3nav.fly_to_bounds(true, true);
            } else {
                c3nav.update_map_state(true);
            }
            c3nav.update_location_labels();
        }

        c3nav.init_locationinputs();


        on('header #user, #about-link, .buttons a', 'click', c3nav.link_handler_modal);


        document.querySelector('header h1 a').removeAttribute('href');

        window.onpopstate = c3nav._onpopstate;

        if (window.mobileclient) {
            c3nav.startWifiScanning();
        }

        c3nav.init_completed = true;
        if (document.visibilityState && document.visibilityState === "hidden") {
            c3nav.on_visibility_change();
        }


    },
    get_csrf_token: function () {
        return document.cookie.match(new RegExp('c3nav_csrftoken=([^;]+)'))[1];
    },

    state: {},
    update_state: function (routing, replace, details, options, nearby) {
        const state = {};
        if (typeof routing === 'boolean') {
            state.routing = routing;
        }
        if (typeof replace === 'boolean') {
            state.replace = replace;
        }
        if (typeof details === 'boolean') {
            state.details = details;
        }
        if (typeof options === 'boolean') {
            state.options = options;
        }
        if (typeof nearby === 'boolean') {
            state.nearby = nearby;
        }
        c3nav.update_state_new(state);
    },
    update_state_new: function ({routing, replace, details, options, nearby} = {}) {
        if (typeof routing !== "boolean") routing = c3nav.state.routing;

        if (details) {
            options = false;
            nearby = false;
        } else if (options) {
            details = false;
            nearby = false;
        } else if (nearby) {
            details = false;
            options = false;
        }

        const new_state = {
                routing: routing,
                origin: c3nav.sidebar.origin.location,
                destination: c3nav.sidebar.destination.location,
                sidebar: true,
                details: !!details,
                options: !!options,
                nearby: !!nearby,
            };

        c3nav._push_state(new_state, replace);

        c3nav._sidebar_state_updated(new_state);
    },
    update_map_state: function (replace, level, center, zoom) {
        var new_state = {
            level: center ? level : c3nav.map.levelControl.currentLevel,
            center: L.GeoJSON.latLngToCoords(center ? center : c3nav.map.center, 2),
            zoom: Math.round((center ? zoom : c3nav.map.zoom) * 100) / 100
        };
        if (!replace) new_state.sidebar = false;

        c3nav._push_state(new_state, replace);
    },
    _first_sidebar_state: true,
    _sidebar_state_updated: function (state, nofly) {
        var view;
        if (state.routing) {
            view = (!state.origin || !state.destination) ? 'route-search' : 'route-result';
        } else {
            view = state.destination ? 'location' : 'search';
            if (state.origin) {
                c3nav.sidebar.origin.set(null);
            }
        }
        c3nav._view = view;

        if (view === 'location' && state.details) {
            c3nav.sidebar.locationDetails.load(state.destination);
        } else {
            c3nav.sidebar.locationDetails.id = null;
            c3nav._clear_detail_layers();
        }

        if (view === 'route-result') {
            if (state.route_result) {
                c3nav._display_route_result(state.route_result, nofly);
                c3nav.sidebar.routeOptions.setOptions(state.route_options);
            } else {
                c3nav.load_route(state.origin, state.destination, nofly);
            }
        } else {
            c3nav.sidebar.routeSummary.origin = null;
            c3nav.sidebar.routeSummary.destination = null;
            c3nav._clear_route_layers();
        }

        const $main = document.querySelector('main');
        $main.dataset.view = view;
        $main.classList.toggle('show-details', !!state.details)
        $main.classList.toggle('show-options', !!state.options);

        if (c3nav._gridLayer) {
            window.setTimeout(function () {
                c3nav._gridLayer._updateGrid();
            }, 300);
        }

        var $search = document.querySelector('#search');
        $search.classList.remove('loading');

        var $selected_locationinputs = $('.locationinput.selected');
        $selected_locationinputs.filter(':focus').blur();
        if (!c3nav._first_sidebar_state || !window.mobileclient) {
            $('#destination-input, [data-view^=route] #origin-input').filter(':not(.selected)').find('input').first().focus();
        }
        if (!$selected_locationinputs.filter(':focus').length) {
            $search.classList.remove('focused');
        }
        c3nav._first_sidebar_state = false;

        c3nav.update_map_locations();
    },
    _clear_route_layers: function () {
        c3nav.map.firstRouteLevel = null;
        c3nav.map.routeLayerBounds = {};
        for (var id in c3nav.map.routeLayers) {
            c3nav.map.routeLayers[id].clearLayers();
        }
    },
    _clear_detail_layers: function () {
        for (var id in c3nav.map.detailLayers) {
            c3nav.map.detailLayers[id].clearLayers();
        }
    },

    update_location_labels: function () {
        if (!c3nav.map.labelControl.labelsActive) return;
        c3nav.map.labelLayer.clearLayers();
        var labels = c3nav.labels[c3nav.map.levelControl.currentLevel],
            bounds = c3nav.map.view_bounds.pad(0.15),
            zoom = c3nav.map.zoom;
        if (!labels) return;

        var valid_upper = [], location, label;
        for (var item of labels) {
            location = item[0];
            label = item[1];
            if (zoom < (location.label_settings.min_zoom || -10)) {
                // since the labels are sorted by min_zoom, we can just leave here
                break;
            }
            if (bounds.contains(label.getLatLng())) {
                if ((location.label_settings.max_zoom || 10) > zoom) {
                    c3nav.map.labelLayer._maybeAddLayerToRBush(label);
                } else {
                    valid_upper.unshift(label);
                }
            }
        }
        for (label of valid_upper) {
            c3nav.map.labelLayer._maybeAddLayerToRBush(label);
        }

    },

    next_route_options: null,
    load_route: function (origin, destination, nofly) {
        if (c3nav.next_route_options || c3nav.sidebar.routeSummary.origin !== origin.id || c3nav.sidebar.routeSummary.destination !== destination.id) {
            c3nav._clear_route_layers();
            c3nav.sidebar.routeSummary.setLoading(true);
            c3nav.sidebar.routeSummary.origin = origin.id;
            c3nav.sidebar.routeSummary.destination = destination.id;
            c3nav.sidebar.routeDetails.setLoading(true);
            c3nav.sidebar.routeOptions.setLoading(true);
            $.post('/api/routing/route/', $.extend({
                'origin': origin.id,
                'destination': destination.id,
                'csrfmiddlewaretoken': c3nav.get_csrf_token()
            }, c3nav.next_route_options || {}), function (data) {
                c3nav._route_loaded(data, nofly)
            }, 'json').fail(function (data) {
                c3nav._route_loaded({
                    'error': `Error ${data.status}`
                })
            });
        }
        c3nav.next_route_options = null;
    },
    _route_loaded: function (data, nofly) {
        if (data.error && c3nav.sidebar.routeSummary.isLoading()) {
            c3nav.sidebar.routeSummary.setError(data.error);
            return;
        }
        if (c3nav.sidebar.routeSummary.origin !== data.request.origin || c3nav.sidebar.routeSummary.destination !== data.request.destination) {
            // loaded too late, information no longer needed
            return;
        }
        c3nav.sidebar.routeDetails.setIssueUrl(data.report_issue_url);
        c3nav._push_state({route_result: data.result, route_options: data.options}, true);
        c3nav._display_route_result(data.result, nofly);
        c3nav.sidebar.routeOptions.setOptions(data.options);
    },
    _display_route_result: function (result, nofly) {
        var first_primary_level = null,
            last_primary_level = null,
            level_collect = [],
            next_level_collect = [],
            in_intermediate_level = true,
            item, coords, description;
        c3nav._clear_route_layers();


        c3nav.sidebar.routeDetails.setRoute(result);
        for (var i = 0; i < result.items.length; i++) {
            item = result.items[i];

            coords = [item.coordinates[0], item.coordinates[1]];
            level_collect.push(coords);
            if (item.level) {
                if (in_intermediate_level) {
                    // if we were in a secondary level, collect this line for the next primary level
                    next_level_collect = next_level_collect.concat(level_collect);
                } else if (last_primary_level) {
                    // if we were in an primary level, add this line to it
                    if (!item.level.on_top_of) {
                        // directly from primary level to primary level
                        c3nav._add_line_to_route(last_primary_level, level_collect.slice(0, -1));
                    } else {
                        c3nav._add_line_to_route(last_primary_level, level_collect);
                    }
                }

                if (item.level.on_top_of) {
                    // if we area now in an secondary level, note this
                    in_intermediate_level = true;
                } else {
                    // if we are now in a primary level, add intermediate lines as links to last primary and this level
                    if (last_primary_level) {
                        if (!in_intermediate_level) {
                            next_level_collect = level_collect.slice(-2);
                        }
                        c3nav._add_line_to_route(last_primary_level, next_level_collect, false, item.level.id);
                        c3nav._add_line_to_route(item.level.id, next_level_collect, false, last_primary_level);
                    }
                    in_intermediate_level = false;
                    if (!first_primary_level) first_primary_level = item.level.id;
                    last_primary_level = item.level.id;
                    next_level_collect = [];
                }
                level_collect = level_collect.slice(-1);
            }
        }
        if (last_primary_level) {
            c3nav._add_line_to_route(last_primary_level, next_level_collect);
            c3nav._add_line_to_route(last_primary_level, level_collect);
        }


        // add origin and destination lines
        c3nav._location_point_overrides = {};
        if (!c3nav._add_location_point_override(result.origin, result.items[0])) {
            c3nav._add_line_to_route(first_primary_level, c3nav._add_intermediate_point(
                result.origin.point.slice(1),
                result.items[0].coordinates.slice(0, 2),
                result.items[1].coordinates.slice(0, 2)
            ), true);
        }
        if (!c3nav._add_location_point_override(result.destination, result.items.slice(-1)[0])) {
            c3nav._add_line_to_route(last_primary_level, c3nav._add_intermediate_point(
                result.destination.point.slice(1),
                result.items[result.items.length - 1].coordinates.slice(0, 2),
                result.items[result.items.length - 2].coordinates.slice(0, 2)
            ).reverse(), true);
        }
        c3nav.update_map_locations();

        c3nav.map.firstRouteLevel = first_primary_level;
        c3nav.sidebar.routeSummary.setSummary(result.summary, result.options_summary);

        if (!nofly) c3nav.fly_to_bounds(true);
    },
    _add_location_point_override: function (location, item) {
        if (location.type === 'level' || location.type === 'space' || location.type === 'area') {
            c3nav._location_point_overrides[location.id] = item.coordinates.slice(0, -1);
            return true;
        }
        return false;
    },
    _add_intermediate_point: function (origin, destination, next) {
        var angle = Math.atan2(destination[1] - next[1], destination[0] - next[0]),
            distance = Math.sqrt(Math.pow(origin[0] - destination[0], 2) + Math.pow(origin[1] - destination[1], 2)),
            offset = Math.min(1.5, distance / 4),
            point = [destination[0] + Math.cos(angle) * offset, destination[1] + Math.sin(angle) * offset];
        return [origin, point, destination];
    },
    _add_line_to_route: function (level, coords, gray, link_to_level) {
        if (coords.length < 2) return;
        var latlngs = L.GeoJSON.coordsToLatLngs(c3nav._smooth_line(coords)),
            routeLayer = c3nav.map.routeLayers[level];
        line = L.polyline(latlngs, {
            color: gray ? '#888888' : c3nav._primary_color,
            dashArray: (gray || link_to_level) ? '7' : null,
            interactive: false,
            smoothFactor: 0.5
        }).addTo(routeLayer);
        bounds = {};
        bounds[level] = line.getBounds();

        c3nav._merge_bounds(c3nav.map.routeLayerBounds, bounds);

        if (link_to_level) {
            L.polyline(latlngs, {
                opacity: 0,
                weight: 15,
                interactive: true
            }).addTo(routeLayer).on('click', function () {
                c3nav.map.levelControl.setLevel(link_to_level);
            });
        }
    },
    _smooth_line: function (coords) {
        if (coords.length > 2) {
            for (var i = 0; i < 4; i++) {
                coords = c3nav._smooth_line_iteration(coords);
            }
        }
        return coords
    },
    _smooth_line_iteration: function (coords) {
        // Chaikin'S Corner Cutting Algorithm
        var new_coords = [coords[0]];
        for (var i = 1; i < coords.length - 1; i++) {
            new_coords.push([(coords[i][0] * 5 + coords[i - 1][0]) / 6, (coords[i][1] * 5 + coords[i - 1][1]) / 6]);
            new_coords.push([(coords[i][0] * 5 + coords[i + 1][0]) / 6, (coords[i][1] * 5 + coords[i + 1][1]) / 6]);
        }
        new_coords.push(coords[coords.length - 1]);
        return new_coords
    },

    _equal_states: function (a, b) {
        if (a.modal !== b.modal) return false;
        if (a.routing !== b.routing || a.details !== b.details || a.options !== b.options) return false;
        if ((a.origin && a.origin.id) !== (b.origin && b.origin.id)) return false;
        if ((a.destination && a.destination.id) !== (b.destination && b.destination.id)) return false;
        if (a.level !== b.level || a.zoom !== b.zoom) return false;
        if (!!a.center !== !!b.center || (a.center && (a.center[0] !== b.center[0] || a.center[1] !== b.center[1]))) return false;
        return true;
    },
    _build_state_url: function (state, embed) {
        return new State(state).build_url(embed);
    },
    _push_state: function (state, replace) {
        state = $.extend({}, c3nav.state, state);
        var old_state = c3nav.state;

        if (!replace && c3nav._equal_states(old_state, state)) return;

        var url = c3nav._build_state_url(state, c3nav.embed),
            embed_link = $('.embed-link');

        if (embed_link.length) {
            embed_link.attr('href', c3nav._build_state_url(state));
        }

        c3nav.state = state;
        if (replace || (!state.sidebar && !old_state.sidebar)) {
            // console.log('state replaced');
            history.replaceState(state, '', url);
        } else {
            // console.log('state pushed');
            history.pushState(state, '', url);
        }

        c3nav.maybe_load_site_update();
    },
    _onpopstate: function (e) {
        // console.log('state popped');
        c3nav.load_state(e.state);
        c3nav.maybe_load_site_update();
    },
    load_state: function (state, nofly) {
        if (state.modal) {
            history.back();
            return;
        }
        state.modal = false;
        c3nav.modal.hide();
        c3nav.sidebar.origin.set(state.origin);
        c3nav.sidebar.destination.set(state.destination);
        c3nav._sidebar_state_updated(state, state.center);
        if (state.center) {
            c3nav.map.levelControl.setLevel(state.level);
            var center = c3nav.map.limitCenter(L.GeoJSON.coordsToLatLng(state.center), state.zoom);
            if (nofly) {
                c3nav.map.setView(center, state.zoom, {animate: false});
            } else {
                c3nav.map.flyTo(center, state.zoom, {duration: 1});
            }
        }
        $.extend(c3nav.state, state);
    },

    _buttons_details_close_click: function () {
        c3nav.update_state(null, null, false);
    },
    _route_buttons_close_click: function () {
        if (c3nav.sidebar.origin.isSelected() && !c3nav.sidebar.destination.isSelected()) {
            c3nav.sidebar.destination.set(c3nav.sidebar.origin.location);
        }
        c3nav.update_state(false);
    },

    // share logic
    _buttons_share_click: function (location) {
        const shareUi = document.querySelector('main > .share-ui').cloneNode(true);
        const state = {...c3nav.state};
        let url;
        if (location.slug) {
            url = `/l/${location.slug}/`;
        } else {
            state.center = null;
            url = c3nav._build_state_url(state);
        }
        shareUi.querySelector('img').src = `/qr${url}`;
        shareUi.querySelector('input').value = `${window.location.protocol}//${window.location.host}${url}`;
        c3nav.modal.open(shareUi);
        if (!window.mobileclient) shareUi.querySelector('input').select();
    },
    // location inputs
    locations: [],
    locations_by_id: {},
    current_locationinput: null,
    last_match_words_key: null,
    init_locationinputs: function () {

        $('.leaflet-control-user-location a').on('click', c3nav._goto_user_location_click).dblclick(function (e) {
            e.stopPropagation();
        });
        $('html').on('focus', '*', c3nav._locationinput_global_focuschange)
            .on('mousedown', '*', c3nav._locationinput_global_focuschange);
    },
    _build_location_html: function (location) {
        return <div className="location" data-id={location.id} data-location={JSON.stringify(location)}>
            <i className="icon material-icons">{c3nav._map_material_icon(location.icon || 'place')}</i>
            <span>{location.title}</span>
            <small>{location.subtitle}</small>
        </div>;
    },
    _build_location_label: function (location) {
        var text = location.label_override || location.title, segments = [''], new_segments = [], new_text = [''],
            len = 0, since_last = 0;
        segments = text.split(' ');
        for (var segment of segments) {
            if (segment.length > 12) {
                new_segments.push('');
                for (char of segment) {
                    new_segments[new_segments.length - 1] += char;
                    since_last++;
                    if ('.,-:;!?/&'.indexOf(char) >= 0) {
                        new_segments.push('');
                    }
                }
                new_segments[new_segments.length - 1] += ' ';
            } else {
                new_segments.push(segment + ' ');
            }
        }
        for (var segment of new_segments) {
            if (len === 0 || len + segment.length < 12) {
                new_text[new_text.length - 1] += $('<div>').text(segment).html();
                len += segment.length;
            } else {
                new_text.push(segment);
                len = segment.length;
            }
        }
        for (var i = 0; i < new_text.length; i++) {
            new_text[i] = new_text[i].trim();
        }
        var html = $('<div class="location-label-text">').append($('<span>').html('&#8239;' + new_text.join('&#8239;<br>&#8239;') + '&#8239;'));
        html.css('font-size', location.label_settings.font_size + 'px');
        return L.marker(L.GeoJSON.coordsToLatLng(location.point.slice(1)), {
            icon: L.divIcon({
                html: html[0].outerHTML,
                iconSize: null,
                className: 'location-label'
            }),
            interactive: false,	// Post-0.7.3
            clickable: false	//      0.7.3
        });
    },
    _locationinput_global_focuschange: function (e) {
        // when focus changed, reset autocomplete if it is outside of locationinputs or autocomplete
        if (c3nav.current_locationinput && !$(e.target).is('#autocomplete *, #' + c3nav.current_locationinput + ' *')) {
            c3nav.sidebar.autocomplete.reset();
        }
        if (!$(e.target).is('.leaflet-popup *')) {
            c3nav.map.remove_popup();
        }
        if (!$(e.target).is('#search *')) {
            c3nav.sidebar.unfocusSearch();
        } else if ($(e.target).is('.locationinput input')) {
            c3nav.sidebar.focusSearch();
        }
    },

    _locationinput_matches_compare: function (a, b) {
        if (a[1] !== b[1]) return b[1] - a[1];
        if (a[2] !== b[2]) return b[2] - a[2];
        if (a[3] !== b[3]) return b[3] - a[3];
        if (a[4] !== b[4]) return b[4] - a[4];
        return a[5] - b[5];
    },

    choose_random_location: function() {
        var possible_locations = new Set();
        for (var id of c3nav.random_location_groups) {
            var group = c3nav.locations_by_id[id];
            if (!group) continue;
            group.locations.forEach(subid => {
                if (subid in c3nav.locations_by_id) possible_locations.add(subid)
            });
        }
        possible_locations = Array.from(possible_locations);
        return c3nav.locations_by_id[possible_locations[Math.floor(Math.random() * possible_locations.length)]];
    },

     link_handler_modal: function (e, el) {
        var location = el.href;
        if (el.target || location.startsWith('/control/')) {
            el.target = '_blank';
            return;
        }
        e.preventDefault();
        e.stopPropagation();
        c3nav.modal.open();
        c3nav.modal.load(fetch(location));
    },

    // map
    init_map: function () {
        var $map = $('#map'),
            $main = $('main'),
            i;

        c3nav.tile_server = $map.attr('data-tile-server');


        c3nav.map = new Map(document.querySelector('#map'));

        c3nav.map.init({
            width: $main.width() - 40,
            height: $main.height() - 250,
        });


        // set up icons
        L.Icon.Default.imagePath = '/static/leaflet/images/';
        c3nav._add_icon('origin');
        c3nav._add_icon('destination');
        c3nav._add_icon('nearby');

        c3nav.schedule_fetch_updates();

    },
    _latlng_to_name: function (latlng) {
        var level = c3nav.map.levelControl.currentLevel;
        const lng = Math.round(latlng.lng * 100) / 100;
        const lat = Math.round(latlng.lat * 100) / 100;
        return `c:${c3nav.map.level_labels_by_id[level]}:${lng}:${lat}`;
    },
    _add_icon: function (name) {
        c3nav[name + 'Icon'] = new L.Icon({
            iconUrl: '/static/img/marker-icon-' + name + '.png',
            iconRetinaUrl: '/static/img/marker-icon-' + name + '-2x.png',
            shadowUrl: '/static/leaflet/images/marker-shadow.png',
            iconSize: [25, 41],
            iconAnchor: [12, 41],
            popupAnchor: [1, -34],
            tooltipAnchor: [16, -28],
            shadowSize: [41, 41]
        });
    },
    visible_map_locations: [],
    update_map_locations: function () {
        // update locations markers on the map
        var origin = c3nav.sidebar.origin.location,
            destination = c3nav.sidebar.destination.location,
            single = !$('main').is('[data-view^=route]'),
            bounds = {};
        for (var level_id in c3nav.map.locationLayers) {
            c3nav.map.locationLayers[level_id].clearLayers()
        }
        c3nav._visible_map_locations = [];
        if (origin) c3nav._merge_bounds(bounds, c3nav.map.add_location(origin, single ? new L.Icon.Default() : c3nav.originIcon));
        if (destination) c3nav._merge_bounds(bounds, c3nav.map.add_location(destination, single ? new L.Icon.Default() : c3nav.destinationIcon));
        var done = [];
        if (c3nav.state.nearby && destination && 'areas' in destination) {
            if (destination.space) {
                c3nav._merge_bounds(bounds, c3nav.map.add_location(c3nav.locations_by_id[destination.space], c3nav.nearbyIcon, true));
            }
            if (destination.near_area) {
                done.push(destination.near_area);
                c3nav._merge_bounds(bounds, c3nav.map.add_location(c3nav.locations_by_id[destination.near_area], c3nav.nearbyIcon, true));
            }
            for (var area of destination.areas) {
                done.push(area);
                c3nav._merge_bounds(bounds, c3nav.map.add_location(c3nav.locations_by_id[area], c3nav.nearbyIcon, true));
            }
            for (var location of destination.nearby) {
                if (location in done) continue;
                c3nav._merge_bounds(bounds, c3nav.map.add_location(c3nav.locations_by_id[location], c3nav.nearbyIcon, true));
            }
        }
        c3nav.map.locationLayerBounds = bounds;
    },
    fly_to_bounds: function (replace_state, nofly) {
        // fly to the bounds of the current overlays
        var level = c3nav.map.levelControl.currentLevel,
            bounds = null;

        if (c3nav.map.firstRouteLevel) {
            level = c3nav.map.firstRouteLevel;
            bounds = c3nav.map.routeLayerBounds[level];
        } else if (c3nav.map.locationLayerBounds[level]) {
            bounds = c3nav.map.locationLayerBounds[level];
        } else {
            for (var level_id in c3nav.map.locationLayers) {
                if (c3nav.map.locationLayerBounds[level_id]) {
                    bounds = c3nav.map.locationLayerBounds[level_id];
                    level = level_id
                }
            }
        }
        c3nav.map.levelControl.setLevel(level);
        if (bounds) {
            var target = c3nav.map.getBoundsCenterZoom(bounds, c3nav._add_map_padding({}));
            var center = c3nav.map.limitCenter(target.center, target.zoom);
            if (nofly) {
                c3nav.map.flyTo(center, target.zoom, {animate: false});
            } else {
                c3nav.map.flyTo(center, target.zoom, {duration: 1});
            }

            if (replace_state) {
                c3nav.update_map_state(true, level, center, target.zoom);
            }
        }
    },
    _add_map_padding: function (options, topleft, bottomright) {
        // add padding information for the current ui layout to fitBounds options
        var $search = $('#search'),
            $main = $('main'),
            padBesideSidebar = (
                $main.width() > 1000 &&
                ($main.height() < 250 || c3nav.state.details || c3nav.state.options)
            ),
            left = padBesideSidebar ? ($search.width() || 0) + 10 : 0,
            top = padBesideSidebar ? 10 : ($search.height() || 0) + 10;
        if ('maxWidth' in options) {
            options.maxWidth = Math.min(options.maxWidth, $main.width() - left - 13 - 50)
        }
        options[topleft || 'paddingTopLeft'] = L.point(left + 13, top + 41);
        options[bottomright || 'paddingBottomRight'] = L.point(50, 20);
        return options;
    },
    _location_point_overrides: {},
    _merge_bounds: function (bounds, new_bounds) {
        for (var level_id in new_bounds) {
            bounds[level_id] = bounds[level_id] ? bounds[level_id].extend(new_bounds[level_id]) : new_bounds[level_id];
        }
    },
    _dynamic_location_loaded: function (data) {
        if (c3nav.sidebar.origin.maybe_set(data) || c3nav.sidebar.destination.maybe_set(data)) {
            c3nav.update_state();
            c3nav.fly_to_bounds(true);
        }
    },

    _location_geometry_loaded: function (data) {
        if (c3nav._visible_map_locations.indexOf(data.id) === -1 || data.geometry === null || data.level === null) return;

        if (data.geometry.type === "Point") return;
        L.geoJSON(data.geometry, {
            style: {
                color: c3nav._primary_color,
                fillOpacity: 0.2,
                interactive: false,
            }
        }).addTo(c3nav.map.locationLayers[data.level]);
    },

    _fetch_updates_timer: null,
    schedule_fetch_updates: function (timeout) {
        if (c3nav._fetch_updates_timer === null) {
            c3nav._fetch_updates_timer = window.setTimeout(c3nav.fetch_updates, timeout || 20000);
        }
    },
    _fetch_updates_failure_count: 0,
    fetch_updates: function () {
        c3nav._fetch_updates_timer = null;
        $.get('/api/updates/fetch/', c3nav._fetch_updates_callback).fail(function () {
            c3nav._fetch_updates_failure_count++;
            waittime = Math.min(5 + c3nav._fetch_updates_failure_count * 5, 120);
            // console.log('fetch updates failed, retying in ' + waittime + 'sec');
            c3nav.schedule_fetch_updates(waittime * 1000);
        });
    },
    _fetch_updates_callback: function (data) {
        c3nav._fetch_updates_failure_count = 0;
        c3nav.schedule_fetch_updates();
        if (c3nav.last_site_update !== data.last_site_update) {
            c3nav.new_site_update = true;
            c3nav.last_site_update = data.last_site_update;
            c3nav.maybe_load_site_update();
        }
        c3nav._set_user_data(data.user);
    },
    maybe_load_site_update: function () {
        if (c3nav.new_site_update && !c3nav.state.modal && (!c3nav.state.routing || !c3nav.state.origin || !c3nav.state.destination)) {
            c3nav._load_site_update();
        }
    },
    _load_site_update: function () {
        $('#modal-content').css({ // TODO: what is this for
            width: 'auto',
            minHeight: 0
        });
        c3nav.modal.open(document.querySelector('#reload-msg').cloneNode(true).childNodes, true);
        window.location.reload();
    },
    _set_user_data: function (data) {
        c3nav.user_data = data;
        var $user = $('header #user');
        $user.find('span').text(data.title);
        $user.find('small').text(data.subtitle || '');
        $('.position-buttons').toggle(data.has_positions);
        if (window.mobileclient) mobileclient.setUserData(JSON.stringify(data));
    },

    _hasLocationPermission: undefined,
    hasLocationPermission: function (nocache) {
        if (c3nav._hasLocationPermission === undefined || (nocache !== undefined && nocache === true)) {
            c3nav._hasLocationPermission = window.mobileclient && (typeof window.mobileclient.hasLocationPermission !== 'function' || window.mobileclient.hasLocationPermission())
        }
        return c3nav._hasLocationPermission;
    },

    getWifiScanRate: function () {
        if (mobileclient.getWifiScanRate) {
            return mobileclient.getWifiScanRate() * 1000;
        }
        // stay compatible to older app versions
        return 30000;

    },
    _wifiScanningTimer: null,
    startWifiScanning: function () {
        if (c3nav._wifiScanningTimer == null) {
            console.log("started wifi scanning with interval of " + c3nav.getWifiScanRate());
            c3nav._wifiScanningTimer = window.setInterval(function () {
                mobileclient.scanNow();
            }, c3nav.getWifiScanRate());
        }
    },
    stopWifiScanning: function () {
        if (c3nav._wifiScanningTimer !== null) {
            window.clearInterval(c3nav._wifiScanningTimer);
            c3nav._wifiScanningTimer = null;
        }
    },

    _no_wifi_count: 0,
    _wifi_scan_results: function (data) {
        data = JSON.parse(data);

        if (data.length) {
            c3nav._hasLocationPermission = true;
        } else {
            c3nav.hasLocationPermission(true);
        }

        var now = Date.now();
        if (now - 4000 < c3nav._last_wifi_scan) return;

        if (c3nav.ssids) {
            var newdata = [];
            for (var i = 0; i < data.length; i++) {
                if (c3nav.ssids.indexOf(data[i]['ssid']) >= 0) {
                    newdata.push(data[i]);
                }
            }
            data = newdata;
        }

        if (!data.length) {
            if (!c3nav._hasLocationPermission) {
                c3nav._set_user_location(null);
            } else {
                if (c3nav._no_wifi_count > 5) {
                    c3nav._no_wifi_count = 0;
                    c3nav._set_user_location(null);
                } else {
                    c3nav._no_wifi_count++;
                }
            }
            return;
        }
        c3nav._no_wifi_count = 0;

        $.post({
            url: '/api/routing/locate/',
            data: JSON.stringify(data),
            dataType: 'json',
            contentType: 'application/json',
            beforeSend: function (xhrObj) {
                xhrObj.setRequestHeader('X-CSRFToken', c3nav.get_csrf_token());
            },
            success: function (data) {
                c3nav._set_user_location(data.location);
            }
        }).fail(function () {
            c3nav._set_user_location(null);
            c3nav._last_wifi_scan = Date.now() + 20000
        });
    },
    _current_user_location: null,
    _set_user_location: function (location) {
        c3nav._current_user_location = location;
        for (var id in c3nav.map.userLocationLayers) {
            c3nav.map.userLocationLayers[id].clearLayers();
        }
        if (location) {
            $('.locationinput .locate, .leaflet-control-user-location a').text(c3nav._map_material_icon('my_location'));
            var latlng = L.GeoJSON.coordsToLatLng(location.geometry.coordinates);
            for (level in c3nav.map.userLocationLayers) {
                if (!c3nav.map.userLocationLayers.hasOwnProperty(level)) continue;
                layer = c3nav.map.userLocationLayers[level];
                factor = (parseInt(level) === location.level) ? 1 : 0.3;
                L.circleMarker(latlng, {
                    radius: 11,
                    stroke: 0,
                    fillOpacity: 0.1
                }).addTo(layer);
                L.circleMarker(latlng, {
                    radius: 5,
                    stroke: 0,
                    fillOpacity: 1 * factor
                }).addTo(layer);
            }
            $('.leaflet-control-user-location a').toggleClass('control-disabled', false);
        } else if (c3nav.hasLocationPermission()) {
            $('.locationinput .locate, .leaflet-control-user-location a').text(c3nav._map_material_icon('location_searching'));
            $('.leaflet-control-user-location a').toggleClass('control-disabled', false);
        } else {
            $('.locationinput .locate, .leaflet-control-user-location a').text(c3nav._map_material_icon('location_disabled'));
            $('.leaflet-control-user-location a').toggleClass('control-disabled', true);
        }
        if (window.mobileclient) {
            if (mobileclient.isCurrentLocationRequested && mobileclient.isCurrentLocationRequested()) {
                if (location) {
                    c3nav._goto_user_location_click();
                } else {
                    mobileclient.currentLocationRequesteFailed()
                }
            }
        }
    },
    _goto_user_location_click: async function (e) {
        e.preventDefault();
        if (!window.mobileclient) {
            c3nav.modal.open(document.querySelector('#app-ad').cloneNode(true).childNodes);
            return;
        }
        if (typeof window.mobileclient.checkLocationPermission === 'function') {
            window.mobileclient.checkLocationPermission(true);
        }
        if (c3nav._current_user_location) {
            c3nav.map.levelControl.setLevel(c3nav._current_user_location.level);
            c3nav.map.flyTo(L.GeoJSON.coordsToLatLng(c3nav._current_user_location.geometry.coordinates), 3, {duration: 1});
        }
    },

    _material_icons_codepoints: null,
    load_material_icons_if_needed: function () {
        // load material icons codepoint for android 4.3.3 and other heccing old browsers
        var elem = document.createElement('span'),
            before = elem.style.fontFeatureSettings,
            ligaturesSupported = false;
        if (before !== undefined) {
            elem.style.fontFeatureSettings = '"liga" 1';
            ligaturesSupported = (elem.style.fontFeatureSettings !== before);
        }
        if (!ligaturesSupported) {
            $.get('/static/material-icons/codepoints', c3nav._material_icons_loaded);
        }
    },
    _material_icons_loaded: function (data) {
        var lines = data.split("\n"),
            line, result = {};

        for (var i = 0; i < lines.length; i++) {
            line = lines[i].split(' ');
            if (line.length === 2) {
                result[line[0]] = String.fromCharCode(parseInt(line[1], 16));
            }
        }
        c3nav._material_icons_codepoints = result;
        $('.material-icons').each(function () {
            $(this).text(c3nav._map_material_icon($(this).text()));
        });
    },
    _map_material_icon: function (name) {
        if (c3nav._material_icons_codepoints === null) return name;
        return c3nav._material_icons_codepoints[name] || '';
    },
    _pause: function () {
        if (c3nav._fetch_updates_timer !== null) {
            window.clearTimeout(c3nav._fetch_updates_timer);
            c3nav._fetch_updates_timer = null;
        }
        if (c3nav._searchable_locations_timer !== null) {
            window.clearTimeout(c3nav._searchable_locations_timer)
            c3nav._searchable_locations_timer = null;
        }
    },
    _resume: function () {
        if (c3nav._fetch_updates_timer === null) {
            console.log("c3nav._resume() -> fetch_updates");
            c3nav.fetch_updates();
        }
        if (c3nav._searchable_locations_timer === null) {
            scheduled_load_in = null
            if (c3nav._last_time_searchable_locations_loaded !== null) {
                scheduled_load_in = c3nav._last_time_searchable_locations_loaded + c3nav._searchable_locations_interval - Date.now();
            }
            if (scheduled_load_in === null || scheduled_load_in <= 5000) {
                c3nav.load_searchable_locations();
                console.log("c3nav._resume() -> loading searchable locations");
            } else {
                c3nav._searchable_locations_timer = window.setTimeout(c3nav.load_searchable_locations, scheduled_load_in);
                console.log("c3nav._resume() -> scheduling searchable locations timeout: " + scheduled_load_in);
            }
        }
    },
    _visibility_hidden_timer: null,
    on_visibility_change: function () {
        if (document.visibilityState === "hidden") {
            c3nav._visibility_hidden_timer = window.setTimeout(function () {
                c3nav._visibility_hidden_timer = null;
                if (document.visibilityState === "hidden") {
                    c3nav._pause();
                }
            }, 30000);
        } else {
            if (c3nav._visibility_hidden_timer !== null) {
                window.clearTimeout(c3nav._visibility_hidden_timer);
            }
            c3nav._resume();
        }
    }
};
$(document).ready(c3nav.init);

function nearby_stations_available() {
    c3nav._wifi_scan_results(mobileclient.getNearbyStations());
}

function openInModal(location) {
    c3nav.modal.open();
    c3nav.modal.load(fetch(location));
}

function mobileclientOnPause() {
    c3nav.stopWifiScanning();
    c3nav._pause();
}

function mobileclientOnResume() {
    c3nav.startWifiScanning();
    c3nav._resume();
}



