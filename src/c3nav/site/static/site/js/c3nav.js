(function () {
    /*
     * Workaround for 1px lines appearing in some browsers due to fractional transforms
     * and resulting anti-aliasing.
     * https://github.com/Leaflet/Leaflet/issues/3575
     */
    const originalInitTile = L.GridLayer.prototype._initTile;
    L.GridLayer.include({
        _initTile: function (tile) {
            originalInitTile.call(this, tile);

            const tileSize = this.getTileSize();

            tile.style.width = tileSize.x + 1 + 'px';
            tile.style.height = tileSize.y + 1 + 'px';
        }
    });

    /*
     * Fix scroll wheel zoom on precise scrolling devices
     */
    const originalPerformZoom = L.Map.ScrollWheelZoom.prototype._performZoom;
    L.Map.ScrollWheelZoom.include({
        _performZoom: function () {
            if (this._delta) this._delta = (this._delta > 0) ? Math.max(this._delta, 60) : Math.min(this._delta, -60);
            originalPerformZoom.call(this);
        }
    });

    /*
     * Polyfill for Math.Log2 because Internet Explorer sucks
     */
    Math.log2 = Math.log2 || function (x) {
        return Math.log(x) * Math.LOG2E;
    };

    const originalGetIconBox = L.LayerGroup.Collision.prototype._getIconBox;
    L.LayerGroup.Collision.prototype._getIconBox = function (el) {
        const result = originalGetIconBox(el);
        const offsetX = (result[2] - result[0] / 2);
        const offsetY = (result[3] - result[1] / 2);
        result[0] -= offsetX;
        result[1] -= offsetY;
        result[2] -= offsetX;
        result[3] -= offsetY;
        return result
    };
}());

function makeClusterIconCreate(color) {
    return function(cluster) {
        const childCount = cluster.getChildCount();
        // TODO: use color based on children?

        const div = document.createElement('div');
        div.style.setProperty('--cluster-marker-color', color);
        const span = document.createElement('span');
        span.innerText = childCount;
        div.append(span);

        return new L.DivIcon({
            html: div,
            className: 'marker-cluster',
            iconSize: new L.Point(30, 30)
        });
    }
}

/**
 * a wrapper for localStorage, catching possible exception when accessing or setting data.
 * working silently if there are errors apart from a console log message when setting an item.
 * does NOT have a in memory storage if localStorage is not available.
 * @type Storage
 */
localStorageWrapper = {
    get length() {
        try {
            return localStorage.length;
        } catch (e) {
            return 0;
        }
    },
    key: function (key) {
        try {
            return localStorage.key(key);
        } catch (e) {
            return null;
        }
    },
    getItem: function (keyName) {
        try {
            return localStorage.getItem(keyName)
        } catch (e) {
            return null;
        }
    },
    setItem: function (keyName, keyValue) {
        try {
            localStorage.setItem(keyName, keyValue)
        } catch (e) {
            console.warn("can't set localstorage preference for " + keyName);
        }
    },
    removeItem: function (keyName) {
        try {
            localStorage.removeItem(keyName)
        } catch (e) {
        }
    },
    clear: function () {
        try {
            localStorage.clear()
        } catch (e) {
        }
    },
};

c3nav = {
    init_completed: false,
    user_data: null,
    init: function () {
        c3nav.access_query = new URLSearchParams(window.location.search).get("access");

        c3nav.load_material_symbols_if_needed();
        c3nav.load_searchable_locations();
        c3nav.load_load_indicator_data();

        $('#messages').find('ul.messages li').each(function () {
            $(this).prepend(
                $('<a href="#" class="close"><i class="material-symbols">close</i></a>').click(function (e) {
                    e.preventDefault();
                    $(this).parent().remove();
                })
            );
        });

        if (!window.mobileclient && !localStorageWrapper.getItem('hideAppAds') && navigator.userAgent.toLowerCase().indexOf("android") > -1 && c3nav.ssids) {
            $('.app-ads').show();
            $('.app-ads .close').click(function () {
                localStorageWrapper.setItem('hideAppAds', true);
                $('.app-ads').remove();
            });
        } else {
            $('.app-ads').remove();
        }

        const $body = $('body');
        if (window.mobileclient) {
            $body.addClass('mobileclient');
            c3nav._set_user_location(null);

            try {
                c3nav._ap_name_mappings = JSON.parse(localStorageWrapper.getItem('c3nav.wifi-scanning.ap-names'));
            } catch (e) {
                // ignore
            }

            if (c3nav._ap_name_mappings === null) {
                c3nav._ap_name_mappings = {};
            }

        } else {
            if (navigator.bluetooth && navigator.bluetooth.getAvailability()) {
                c3nav._set_user_location(null);
            } else {
                c3nav._set_user_location(null);
            }

            document.addEventListener('visibilitychange', c3nav.on_visibility_change, false);
        }

        if ($body.is('[data-user-data]')) {
            c3nav._set_user_data(JSON.parse($body.attr('data-user-data')));
        }


        c3nav.theme = JSON.parse(document.getElementById('c3nav-active-theme').textContent);
        c3nav.themes = JSON.parse(document.getElementById('c3nav-themes').textContent);
    },
    _searchable_locations_timer: null,
    load_searchable_locations: function (firstTime) {
        c3nav._searchable_locations_timer = null;
        c3nav_api.get('map/locations?searchable=true')
            .then(c3nav._searchable_locations_loaded)
            .catch((err) => {
                console.error(err);
                if (c3nav._searchable_locations_timer === null) {
                    c3nav._searchable_locations_timer = window.setTimeout(c3nav.load_searchable_locations, c3nav.init_completed ? 300000 : 15000);
                }
            });
    },
    _load_indicator_timer: null,
    load_load_indicator_data: async function () {
        c3nav._load_indicator_timer = null;
        try {
            const data = await c3nav_api.get('map/load');
            if (data) {
                c3nav._location_load_groups = data;
            }
            c3nav.update_load_data();
        } catch (err) {
            console.error(err);
        }

        if (c3nav._load_indicator_timer === null) {
            c3nav._load_indicator_timer = window.setTimeout(c3nav.load_load_indicator_data, c3nav._load_indicator_interval);
        }

    },
    _sort_labels: function (a, b) {
        let result = (a[0].effective_label_settings.min_zoom || -10) - (b[0].effective_label_settings.min_zoom || -10);
        if (result === 0) {
            result = b[0].effective_label_settings.font_size - a[0].effective_label_settings.font_size;
        }
        return result;
    },
    _last_time_searchable_locations_loaded: null,
    _searchable_locations_interval: 120000,
    _load_indicator_interval: 10000, // TODO: set to a sensible number
    loadIndicatorLocations: [],
    _searchable_locations_loaded: function (data) {
        c3nav._last_time_searchable_locations_loaded = Date.now();
        if (data !== undefined) {
            const locations = [];
            const locations_by_id = {};
            const labels = {};
            const loadIndicatorLocations = [];
            for (let i = 0; i < data.length; i++) {
                const location = data[i];
                location.elem = c3nav._build_location_html(location);
                location.title_words = location.title.toLowerCase().split(/\s+/);
                location.subtitle_words = location.subtitle.toLowerCase().split(/\s+/);
                location.match = ' ' + location.title_words.join(' ') + ' ' + location.subtitle_words.join(' ') + '  ' + location.effective_slug + ' ' + location.add_search.toLowerCase();
                locations.push(location);
                locations_by_id[location.id] = location;
                if (location.point && location.effective_label_settings) {
                    if (!(location.point[0] in labels)) labels[location.point[0]] = [];
                    labels[location.point[0]].push([location, c3nav._build_location_label(location)]);
                }


                if (location.point && location.load_group_display) {
                    loadIndicatorLocations.push({
                        level: location.point[0],
                        coords: location.point.slice(1),
                        load_id: location.load_group_display,
                    });
                }
            }
            for (const level_id in labels) {
                labels[level_id].sort(c3nav._sort_labels);
            }
            c3nav.locations = locations;
            c3nav.locations_by_id = locations_by_id;
            c3nav.labels = labels;
            c3nav.loadIndicatorLocations = loadIndicatorLocations;
            c3nav.update_load_data();
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
    _loadIndicatorLabels: {},
    _location_load_groups: {},
    update_load_data: function() {
        c3nav._loadIndicatorLabels = {};
        for (const location of c3nav.loadIndicatorLocations) {
            const load = c3nav._location_load_groups[location.load_id];
            if (typeof load != "number") continue;

            const load_pct = Math.round(load * 100);

            const html = $(`<div class="location-load-info"><div class="load-indicator" style="--location-load-value: ${load_pct}%;"></div>`);

            const marker = L.marker(L.GeoJSON.coordsToLatLng(location.coords), {
                icon: L.divIcon({
                    html: html[0].outerHTML,
                    iconSize: null,
                    className: ''
                }),
                interactive: false,
            });

            let levelLabels = c3nav._loadIndicatorLabels[location.level];
            if (!levelLabels) {
                levelLabels = c3nav._loadIndicatorLabels[location.level] = [];
            }

            levelLabels.push(marker);
        }

        c3nav._update_loadinfo_labels();
    },
    _update_loadinfo_labels: function () {
        if (!c3nav._loadIndicatorLayer) return;
        c3nav._loadIndicatorLayer.clearLayers();
        if (!c3nav._loadIndicatorControl.enabled) return;
        const labels = c3nav._loadIndicatorLabels[c3nav.current_level()] ?? [];
        const bounds = c3nav.map.getBounds().pad(0.15);
        if (!labels) return;

        for (const label of labels) {
            if (bounds.contains(label.getLatLng())) {
                c3nav._loadIndicatorLayer._maybeAddLayerToRBush(label);
            }
        }
    },

    continue_init: function () {
        c3nav.init_map();

        $('.locationinput').data('location', null);

        const $main = $('main');
        const state = JSON.parse($main.attr('data-state'));

        c3nav.embed = $main.is('[data-embed]');

        c3nav.last_site_update = JSON.parse($main.attr('data-last-site-update'));
        c3nav.new_site_update = false;

        c3nav.ssids = $main.is('[data-ssids]') ? JSON.parse($main.attr('data-ssids')) : null;

        c3nav.random_location_groups = $main.is('[data-random-location-groups]') ? $main.attr('data-random-location-groups').split(',').map(id => parseInt(id)) : null;

        $(document).on('click', '.theme-selection>button', c3nav.select_theme);


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
            c3nav._update_loadinfo_labels();
        }

        c3nav.init_locationinputs();

        $('#location-buttons').find('.route').on('click', c3nav._location_buttons_route_click);

        const $result_buttons = $('#location-buttons, #route-result-buttons');
        $result_buttons.find('.share').on('click', c3nav._buttons_share_click);
        $result_buttons.find('.details').on('click', c3nav._buttons_details_click);
        $('#route-search-buttons, #route-result-buttons').find('.swap').on('click', c3nav._route_buttons_swap_click);
        $('#route-search-buttons').find('.close').on('click', c3nav._route_buttons_close_click);
        $('#route-summary').find('.options').on('click', c3nav._buttons_options_click);

        const $route_options = $('#route-options');
        $route_options.find('.close').on('click', c3nav._route_options_close_click);
        $route_options.find('button').on('click', c3nav._route_options_submit);
        $('#map').on('click', '.location-popup .button-clear', c3nav._popup_button_click);

        $('.details .close').on('click', c3nav._buttons_details_close_click);

        $('#modal').on('click', c3nav._modal_click)
            .on('click', 'a', c3nav._modal_link_click)
            .on('submit', 'form', c3nav._modal_submit)
            .on('click', '.mobileclient-share', c3nav._mobileclient_share_click)
            .on('click', '.mobileclient-shortcut', c3nav._mobileclient_shortcut_click);
        $('header #user, #about-link, .buttons a').on('click', c3nav._modal_link_click);

        $('header h1 a').removeAttr('href');

        window.onpopstate = c3nav._onpopstate;

        if (window.mobileclient) {
            c3nav.startWifiScanning();
            c3nav.startBLEScanning();
        } else if (navigator.bluetooth) {
            c3nav.startBLEScanning();
        }

        c3nav.init_completed = true;
        if (document.visibilityState && document.visibilityState === "hidden") {
            c3nav.on_visibility_change();
        }

        //c3nav.test_location();
    },
    test_location: function () {
        c3nav_api.get('positioning/locate-test')
            .then(data => {
                window.setTimeout(c3nav.test_location, 1000);
                c3nav._set_user_location(data.location);
            })
            .catch(err => {
                console.error(err);
                window.setTimeout(c3nav.test_location, 1000);
                c3nav._set_user_location(null);
            });
    },

    state: {},
    update_state: function (routing, replace, details, options, nearby) {
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

        const destination = $('#destination-input').data('location');
        const origin = $('#origin-input').data('location');
        const new_state = {
            routing: routing,
            origin: origin,
            destination: destination,
            sidebar: true,
            details: !!details,
            options: !!options,
            nearby: !!nearby,
        };

        c3nav._push_state(new_state, replace);

        c3nav._sidebar_state_updated(new_state);
    },
    current_level: function () {
        return c3nav._levelControl.currentLevel || c3nav.resume_level;
    },
    update_map_state: function (replace, level, center, zoom) {
        const new_state = {
            level: center ? level : c3nav.current_level(),
            center: L.GeoJSON.latLngToCoords(center ? center : c3nav.map.getCenter(), 2),
            zoom: Math.round((center ? zoom : c3nav.map.getZoom()) * 100) / 100
        };
        if (!replace) new_state.sidebar = false;

        c3nav._push_state(new_state, replace);
    },
    _first_sidebar_state: true,
    _sidebar_state_updated: function (state, nofly) {
        let view;
        if (state.routing) {
            view = (!state.origin || !state.destination) ? 'route-search' : 'route-result';
        } else {
            view = state.destination ? 'location' : 'search';
            if (state.origin) {
                c3nav._locationinput_set($('#origin-input'), null);
            }
        }
        c3nav._view = view;

        if (view === 'location' && state.details) {
            c3nav.load_location_details(state.destination);
        } else {
            $('#location-details').removeAttr('data-id');
            c3nav._clear_detail_layers();
        }

        if (view === 'route-result') {
            if (state.route_result) {
                c3nav._display_route_result(state.route_result, nofly);
                c3nav._display_route_options(state.route_options);
            } else {
                c3nav.load_route(state.origin, state.destination, nofly);
            }
        } else {
            $('#route-summary').removeAttr('data-origin').removeAttr('data-destination');
            c3nav._clear_route_layers();
        }

        $('main').attr('data-view', view)
            .toggleClass('show-details', !!state.details)
            .toggleClass('show-options', !!state.options);

        if (c3nav._gridLayer) {
            window.setTimeout(function () {
                c3nav._gridLayer._updateGrid(c3nav.map);
            }, 300);
        }

        const $search = $('#search');
        $search.removeClass('loading');

        const $selected_locationinputs = $('.locationinput.selected');
        $selected_locationinputs.filter(':focus').blur();
        if (!c3nav._first_sidebar_state || !window.mobileclient) {
            $('#destination-input, [data-view^=route] #origin-input').filter(':not(.selected)').find('input').first().focus();
        }
        if (!$selected_locationinputs.filter(':focus').length) {
            $search.removeClass('focused');
        }
        c3nav._first_sidebar_state = false;

        c3nav.update_map_locations();
    },
    _clear_route_layers: function () {
        c3nav._firstRouteLevel = null;
        c3nav._routeLayerBounds = {};
        for (const id in c3nav._routeLayers) {
            c3nav._routeLayers[id].clearLayers();
        }
    },
    _clear_detail_layers: function () {
        for (const id in c3nav._detailLayers) {
            c3nav._detailLayers[id].clearLayers();
        }
    },

    update_location_labels: function () {
        if (!c3nav._labelControl.enabled) return;
        c3nav._labelLayer.clearLayers();
        const labels = c3nav.labels[c3nav.current_level()];
        const bounds = c3nav.map.getBounds().pad(0.15);
        const zoom = c3nav.map.getZoom();
        if (!labels) return;

        const valid_upper = [];
        for (const item of labels) {
            const location = item[0];
            const label = item[1];
            if (zoom < (location.effective_label_settings.min_zoom || -10)) {
                // since the labels are sorted by min_zoom, we can just leave here
                break;
            }
            if (bounds.contains(label.getLatLng())) {
                if ((location.effective_label_settings.max_zoom || 10) > zoom) {
                    c3nav._labelLayer._maybeAddLayerToRBush(label);
                } else {
                    valid_upper.unshift(label);
                }
            }
        }

        for (const label of valid_upper) {
            c3nav._labelLayer._maybeAddLayerToRBush(label);
        }
    },

    load_location_details: function (location) {
        const $location_details = $('#location-details');
        if ($location_details.attr('data-id') !== String(location.id)) {
            $location_details.addClass('loading').attr('data-id', location.id);
            c3nav._clear_route_layers();
            c3nav_api.get(`map/locations/${location.id}/display`).then(c3nav._location_details_loaded)
                .catch(data => {
                    console.error(data);
                    const $location_details = $('#location-details');
                    $location_details.find('.details-body').text('Error ' + String(data.status));
                    $location_details.find('.details-body').html('');
                    $location_details.find('.editor').hide();
                    $location_details.find('.report').hide();
                    $location_details.find('.external-url-button').hide();
                    $location_details.removeClass('loading');
                })
        }
    },
    _location_details_loaded: function (data) {
        const $location_details = $('#location-details');
        if ($location_details.attr('data-id') !== String(data.id)) {
            // loaded too late, information no longer needed
            return;
        }

        const elem = $('<dl>');
        for (let i = 0; i < data.display.length; i++) {
            const line = data.display[i];
            elem.append($('<dt>').text(line[0]));
            if (typeof line[1] === 'string') {
                elem.append($('<dd>').text(line[1]));
            } else if (line[1] === null || line.length === 0) {
                elem.append($('<dd>').text('-'));
            } else if (line.length === 2 && line[1].url !== undefined) {
                const loclist = $('<dd>');
                loclist.append($('<a>').attr('href', line[1].url).attr('target', '_blank').text(line[1].title));
                elem.append(loclist);
            } else {
                const sublocations = (line[1].length === undefined) ? [line[1]] : line[1];
                const loclist = $('<dd>');
                for (let j = 0; j < sublocations.length; j++) {
                    const loc = sublocations[j];
                    if (loc.can_search) {
                        loclist.append($('<a>').attr('href', '/l/' + loc.effective_slug + '/details/').attr('data-id', loc.id).click(function (e) {
                            e.preventDefault();
                            c3nav._locationinput_set($('#destination-input'), c3nav.locations_by_id[parseInt($(this).attr('data-id'))]);
                            c3nav.update_state(false, false, true);
                        }).text(loc.title));
                    } else {
                        loclist.append($('<span>').text(loc.title));
                    }
                }
                elem.append(loclist);
            }
        }
        $location_details.find('.details-body').html('').append(elem);

        const $editor = $location_details.find('.editor');
        if (data.editor_url) {
            $editor.attr('href', data.editor_url).show();
        } else {
            $editor.hide();
        }

        if (data.geometry) {
            const report_url = '/report/l/' + String(data.id) + '/';
            $location_details.find('.report').attr('href', report_url);
        } else {
            $location_details.find('.report').hide();
        }

        if (data.external_url) {
            $location_details.find('.external-url-button a').attr('href', data.external_url.url);
            $location_details.find('.external-url-button span').text(data.external_url.title);
        } else {
            $location_details.find('.external-url-button').hide();
        }

        if (data.geometry && data.level) {
            L.geoJSON(data.geometry, {
                style: {
                    color: 'var(--color-map-overlay)',
                    fillOpacity: 0.1,
                }
            }).addTo(c3nav._routeLayers[data.level]);
        }
        $location_details.removeClass('loading');
    },
    next_route_options: null,
    session_route_options: null,
    load_route: function (origin, destination, nofly) {
        const $route = $('#route-summary');
        const $details_wrapper = $('#route-details');
        const $options_wrapper = $('#route-options');
        if (c3nav.next_route_options || $route.attr('data-origin') !== String(origin.id) || $route.attr('data-destination') !== String(destination.id)) {
            c3nav._clear_route_layers();
            $route.addClass('loading').attr('data-origin', origin.id).attr('data-destination', destination.id);
            $details_wrapper.addClass('loading');
            $options_wrapper.addClass('loading');
            c3nav_api.post('routing/route', {
                origin: origin.id,
                destination: destination.id,
                options_override: c3nav.next_route_options ?? c3nav.session_route_options ?? null,
            })
                .then(data => c3nav._route_loaded(data, nofly))
                .catch(data => {
                    console.error(data);
                    c3nav._route_loaded({error: `Error ${data.status}`});
                });
        }
        c3nav.next_route_options = null;
    },
    _route_loaded: function (data, nofly) {
        const $route = $('#route-summary');
        if (data.error && $route.is('.loading')) {
            console.error(data.error);
            $route.find('span').text(data.error);
            $route.removeClass('loading');
            return;
        }
        if ($route.attr('data-origin') !== String(data.request.origin) || $route.attr('data-destination') !== String(data.request.destination)) {
            // loaded too late, information no longer needed
            return;
        }
        $('#route-details .report').attr('href', data.report_issue_url);
        c3nav._push_state({route_result: data.result, route_options: data.options_form}, true);
        c3nav._display_route_result(data.result, nofly);
        c3nav._display_route_options(data.options_form);
    },
    _display_route_result: function (result, nofly) {
        const $route = $('#route-summary');
        const $details_wrapper = $('#route-details');
        const $details = $details_wrapper.find('.details-body');
        c3nav._clear_route_layers();

        $details_wrapper.find('.report')

        $details.html('');
        $details.append(c3nav._build_location_html(result.origin));

        let first_primary_level = null;
        let last_primary_level = null;
        let level_collect = [];
        let next_level_collect = [];
        let in_intermediate_level = true;
        for (let i = 0; i < result.items.length; i++) {
            const item = result.items[i];

            for (let j = 0; j < item.descriptions.length; j++) {
                const description = item.descriptions[j];
                $details.append(c3nav._build_route_item(description[0], description[1]));
            }

            const coords = [item.coordinates[0], item.coordinates[1]];
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

        $details.append(c3nav._build_location_html(result.destination));

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

        c3nav._firstRouteLevel = first_primary_level;
        $route.find('span').text(result.summary);
        $route.find('em').text(result.options_summary);
        $route.removeClass('loading');
        $details_wrapper.removeClass('loading');

        if (!nofly) c3nav.fly_to_bounds(true);
    },
    _add_location_point_override: function (location, item) {
        if (location.type === 'level' || location.type === 'space' || location.type === 'area') {
            c3nav._location_point_overrides[location.id] = item.coordinates.slice(0, -1);
            return true;
        }
        return false;
    },
    _build_route_item: function (icon, text) {
        const elem = $('<div class="routeitem">');
        if (icon.indexOf('.') === -1) {
            elem.append($('<span class="icon"><i class="material-symbols">' + icon + '</i></span>'));
        } else {
            elem.append($('<span class="icon"><img src="/static/site/img/icons/' + icon + '"></span>'));
        }
        elem.append($('<span>').text(text));
        return elem;
    },
    _add_intermediate_point: function (origin, destination, next) {
        const angle = Math.atan2(destination[1] - next[1], destination[0] - next[0]);
        const distance = Math.sqrt(Math.pow(origin[0] - destination[0], 2) + Math.pow(origin[1] - destination[1], 2));
        const offset = Math.min(1.5, distance / 4);
        const point = [destination[0] + Math.cos(angle) * offset, destination[1] + Math.sin(angle) * offset];
        return [origin, point, destination];
    },
    _add_line_to_route: function (level, coords, dots, link_to_level) {
        if (coords.length < 2) return;
        const latlngs = L.GeoJSON.coordsToLatLngs(c3nav._smooth_line(coords));
        const routeLayer = c3nav._routeLayers[level];
        const line = L.polyline(latlngs, {
            className: dots ? 'c3nav-route-dashes' : 'c3nav-route-line',
            color: dots ? 'var(--color-route-dashes)' : 'var(--color-map-overlay)',
            dashArray: (dots || link_to_level) ? '7' : null,
            interactive: false,
            smoothFactor: 0.5
        }).addTo(routeLayer);
        const bounds = {};
        bounds[level] = line.getBounds();

        c3nav._merge_bounds(c3nav._routeLayerBounds, bounds);

        if (link_to_level) {
            L.polyline(latlngs, {
                opacity: 0,
                weight: 15,
                interactive: true
            }).addTo(routeLayer).on('click', function () {
                c3nav._levelControl.setLevel(link_to_level);
            });
        }
    },
    _smooth_line: function (coords) {
        if (coords.length > 2) {
            for (let i = 0; i < 4; i++) {
                coords = c3nav._smooth_line_iteration(coords);
            }
        }
        return coords
    },
    _smooth_line_iteration: function (coords) {
        // Chaikin'S Corner Cutting Algorithm
        const new_coords = [coords[0]];
        for (let i = 1; i < coords.length - 1; i++) {
            new_coords.push([(coords[i][0] * 5 + coords[i - 1][0]) / 6, (coords[i][1] * 5 + coords[i - 1][1]) / 6]);
            new_coords.push([(coords[i][0] * 5 + coords[i + 1][0]) / 6, (coords[i][1] * 5 + coords[i + 1][1]) / 6]);
        }
        new_coords.push(coords[coords.length - 1]);
        return new_coords
    },
    _display_route_options: function (options) {
        const $options_wrapper = $('#route-options');
        const $options = $options_wrapper.find('.route-options-fields');
        $options.html('');
        for (let i = 0; i < options.length; i++) {
            // TODO: I think this logic is broken, field is only assigned for type=select but always used
            const option = options[i];
            const field_id = 'option_id_' + option.name;
            $options.append($('<label for="' + field_id + '">').text(option.label));
            let field;
            if (option.type === 'select') {
                field = $('<select name="' + option.name + '" id="' + field_id + '">');
                for (let j = 0; j < option.choices.length; j++) {
                    const choice = option.choices[j];
                    field.append($('<option value="' + choice.name + '">').text(choice.title));
                }
            }
            field.val(option.value);
            $options.append(field);
        }
        $options_wrapper.removeClass('loading');
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
        let url = embed ? '/embed' : '';
        if (state.routing) {
            if (state.origin) {
                url += (state.destination) ? '/r/' + state.origin.effective_slug + '/' + state.destination.effective_slug + '/' : '/o/' + state.origin.effective_slug + '/';
            } else {
                url += (state.destination) ? '/d/' + state.destination.effective_slug + '/' : '/r/';
            }
        } else {
            url += state.destination ? ('/l/' + state.destination.effective_slug + '/') : '/';
        }
        if (state.details && (url.startsWith('/l/') || url.startsWith('/r/'))) {
            url += 'details/'
        }
        if (state.nearby && url.startsWith('/l/')) {
            url += 'nearby/'
        }
        if (state.options && url.startsWith('/r/')) {
            url += 'options/'
        }
        if (state.center) {
            url += '@' + String(c3nav.level_indices_by_id[state.level]) + ',' + String(state.center[0]) + ',' + String(state.center[1]) + ',' + String(state.zoom);
        }
        return url
    },
    _push_state: function (state, replace) {
        state = $.extend({}, c3nav.state, state);
        const old_state = c3nav.state;

        if (!replace && c3nav._equal_states(old_state, state)) return;

        const url = c3nav._build_state_url(state, c3nav.embed);
        const embed_link = $('.embed-link');

        if (embed_link.length) {
            embed_link.attr('href', c3nav._build_state_url(state) + (c3nav.access_query ? ('?access=' + c3nav.access_query) : ''));
        }

        c3nav.state = state;
        if (replace || (!state.sidebar && !old_state.sidebar)) {
            history.replaceState(state, '', url);
        } else {
            history.pushState(state, '', url);
        }

        c3nav._maybe_load_site_update(state);
    },
    _onpopstate: function (e) {
        c3nav.load_state(e.state);
        c3nav._maybe_load_site_update(e.state);
    },
    load_state: function (state, nofly) {
        const route_options_str = new URLSearchParams(window.location.search).get('route_opts');
        if (route_options_str) {
            try {
                c3nav.session_route_options = JSON.parse(route_options_str);
                if (sessionStorage) {
                    sessionStorage.setItem('session-route-opts', JSON.stringify(c3nav.session_route_options));
                }
            } catch (e) {
                console.error(e);
            }
        } else if (sessionStorage) {
            try {
                c3nav.session_route_options = JSON.parse(sessionStorage.getItem('session-route-opts'));
            } catch (e) {
                console.error(e);
            }
        }

        if (state.modal) {
            history.back();
            return;
        }
        state.modal = false;
        $('#modal').removeClass('show');
        c3nav._locationinput_set($('#origin-input'), state.origin);
        c3nav._locationinput_set($('#destination-input'), state.destination);
        c3nav._sidebar_state_updated(state, state.center);
        if (state.center) {
            c3nav._levelControl.setLevel(state.level);
            const center = c3nav.map._limitCenter(L.GeoJSON.coordsToLatLng(state.center), state.zoom, c3nav.map.options.maxBounds);
            if (nofly) {
                c3nav.map.setView(center, state.zoom, {animate: false});
            } else {
                c3nav.map.flyTo(center, state.zoom, {duration: 1});
            }
        }
        $.extend(c3nav.state, state);
    },

    // button handlers
    _buttons_details_click: function () {
        c3nav.update_state(null, null, !c3nav.state.details);
    },
    _buttons_details_close_click: function () {
        c3nav.update_state(null, null, false);
    },
    _buttons_options_click: function () {
        c3nav.update_state(null, null, null, !c3nav.state.options);
    },
    _route_options_close_click: function () {
        c3nav.update_state(null, null, null, false);
    },
    _route_options_submit: function () {
        const options = {};
        const waytypes = {};
        $('#route-options').find('.route-options-fields [name]').each(function () {
            const name = $(this).attr('name');
            const value = $(this).val();
            if (name.startsWith('waytype_')) {
                waytypes[name.substring('waytype_'.length)] = value;
            } else {
                options[name] = value;
            }
        });
        options.way_types = waytypes;
        if ($(this).is('.save')) {
            c3nav_api.put('routing/options', options);
        }
        c3nav.next_route_options = options;
        c3nav.update_state(null, null, null, false);
    },
    _location_buttons_route_click: function () {
        c3nav.update_state(true);
    },
    _route_buttons_swap_click: function () {
        const $origin = $('#origin-input');
        const $destination = $('#destination-input');
        const tmp = $origin.data('location');
        c3nav._locationinput_set($origin, $destination.data('location'));
        c3nav._locationinput_set($destination, tmp);
        const offset = $destination.position().top - $origin.position().top;
        $origin.stop().css('top', offset).animate({top: 0}, 150);
        $destination.stop().css('top', -offset).animate({top: 0}, 150);
        c3nav.update_state();
    },
    _route_buttons_close_click: function () {
        const $origin = $('#origin-input');
        const $destination = $('#destination-input');
        if ($origin.is('.selected') && !$destination.is('.selected')) {
            c3nav._locationinput_set($destination, $origin.data('location'));
        }
        c3nav.update_state(false);
    },
    _popup_button_click: function (e) {
        e.stopPropagation();
        const $location = $(this).parent().siblings('.location');
        if ($location.length) {
            const location = c3nav.locations_by_id[parseInt($location.attr('data-id'))]
                || JSON.parse($location.attr('data-location'));

            const $origin = $('#origin-input');
            const $destination = $('#destination-input');
            if ($(this).is('.as-location')) {
                c3nav._locationinput_set($destination, location);
                c3nav.update_state(false);
            } else if ($(this).is('.share')) {
                c3nav._buttons_share_click(location);
            } else if ($(this).is('.show-nearby')) {
                c3nav._click_anywhere_load(true);
                return;
            } else if ($(this).is('a')) {
                c3nav._modal_link_click.call(this, e);
            } else {
                const $locationinput = $(this).is('.as-origin') ? $origin : $destination;
                const $other_locationinput = $(this).is('.as-origin') ? $destination : $origin;
                const other_location = $other_locationinput.data('location');
                c3nav._locationinput_set($locationinput, location);
                if (other_location && (other_location.id === location.id || (other_location.locations && other_location.locations.includes(location.id)))) {
                    c3nav._locationinput_set($other_locationinput, null);
                }
                c3nav.update_state(true);
            }
            if (c3nav._click_anywhere_popup) c3nav._click_anywhere_popup.remove();
        }
    },

    // share logic
    _buttons_share_click: function (location) {
        let url = c3nav._get_share_url(false, location);
        if (navigator.share) {
            let title;
            let subtitle;
            if (location.effective_slug) {
                title = location.title;
                subtitle = location.subtitle;
            } else {
                title = c3nav.state.destination.title;
                subtitle = c3nav.state.destination.subtitle;
            }
            const text = title + '\n' + subtitle;
            url = window.location.protocol + '//' + window.location.host + url;
            navigator.share({
                url: url,
                title: title,
                text: text,
            });
        } else {
            c3nav.open_modal($('main > .share-ui')[0].outerHTML);
            c3nav._update_share_ui(url);
        }
    },
    _get_share_url: function (with_position, location) {
        const state = $.extend({}, c3nav.state);
        if (location.effective_slug) {
            return '/l/' + location.effective_slug + '/';
        } else {
            if (!with_position) {
                state.center = null;
            }
            return c3nav._build_state_url(state);
        }
    },
    _update_share_ui: function (url) {
        const $share = $('#modal').find('.share-ui');
        $share.find('img').attr('src', '/qr' + url);
        $share.find('input').val(window.location.protocol + '//' + window.location.host + url);
        if (!window.mobileclient) $share.find('input')[0].select();
    },
    _mobileclient_share_click: function () {
        mobileclient.shareUrl($('#modal').find('.share-ui input').val());
    },
    _mobileclient_shortcut_click: function () {
        mobileclient.createShortcut($('#modal').find('.share-ui input').val(), c3nav.state.destination.title);
    },

    // location inputs
    locations: [],
    locations_by_id: {},
    current_locationinput: null,
    last_match_words_key: null,
    init_locationinputs: function () {

        $('.locationinput input').on('input', c3nav._locationinput_input)
            .on('blur', c3nav._locationinput_blur)
            .on('keydown', c3nav._locationinput_keydown);
        $('.locationinput .clear').on('click', c3nav._locationinput_clear);
        $('.locationinput .locate').toggle(c3nav.ssids !== null).on('click', c3nav._locationinput_locate);
        $('.locationinput .random').on('click', c3nav._random_location_click);
        $('.leaflet-control-user-location a').on('click', c3nav._goto_user_location_click).dblclick(function (e) {
            e.stopPropagation();
        });
        $('#autocomplete').on('mouseover', '.location', c3nav._locationinput_hover_suggestion)
            .on('click', '.location', c3nav._locationinput_click_suggestion);
        $('html').on('focus', '*', c3nav._locationinput_global_focuschange)
            .on('mousedown', '*', c3nav._locationinput_global_focuschange);
        $('html').on('keydown', c3nav._global_keydown);
    },
    _build_location_html: function (location) {
        const html = $('<div class="location">')
            .append($('<i class="icon material-symbols">').text(c3nav._map_material_icon(location.effective_icon || 'place')))
            .append($('<span>').text(location.title))
            .append($('<small>').text(location.subtitle)).attr('data-id', location.id);
        html.attr('data-location', JSON.stringify(location));
        return html[0].outerHTML;
    },
    _build_location_label: function (location) {
        const text = location.label_override || location.title;
        const new_segments = [];
        const new_text = [''];
        let len = 0;
        let since_last = 0;
        const segments = text.split(' ');
        for (const segment of segments) {
            if (segment.length > 12) {
                new_segments.push('');
                for (const char of segment) {
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
        for (const  segment of new_segments) {
            if (len === 0 || len + segment.length < 12) {
                new_text[new_text.length - 1] += $('<div>').text(segment).html();
                len += segment.length;
            } else {
                new_text.push($('<div>').text(segment).html());
                len = segment.length;
            }
        }
        for (let i = 0; i < new_text.length; i++) {
            new_text[i] = new_text[i].trim();
        }


        const html = $('<div class="location-label-text">').append($('<span>').html('&#8239;' + new_text.join('&#8239;<br>&#8239;') + '&#8239;'));
        html.css('font-size', location.effective_label_settings.font_size + 'px');
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
    _locationinput_set: function (elem, location) {
        // set a location input
        if (location && location.elem === undefined) location.elem = c3nav._build_location_html(location);
        c3nav._locationinput_reset_autocomplete();
        elem.toggleClass('selected', !!location).toggleClass('empty', !location)
            .data('location', location).data('lastlocation', location).removeData('suggestion');
        elem.find('.icon').text(location ? c3nav._map_material_icon(location.effective_icon || 'place') : '');
        elem.find('input').val(location ? location.title : '').removeData('origval');
        elem.find('small').text(location ? location.subtitle : '');
    },
    _locationinput_reset: function (elem) {
        // reset this locationinput to its last location
        c3nav._locationinput_set(elem, elem.data('lastlocation'));
        c3nav.update_state();
    },
    _locationinput_clear: function () {
        // clear this locationinput
        c3nav._locationinput_set($(this).parent(), null);
        c3nav.update_state();
        $(this).parent().find('input').focus();
    },
    _locationinput_locate: function (e) {
        e.preventDefault();
        if (window.mobileclient) {
            if (typeof window.mobileclient.checkLocationPermission === 'function') {
                window.mobileclient.checkLocationPermission(true);
            }
        } else if (navigator.bluetooth) {
            c3nav.startBLEScanning();
        } else {
            c3nav.open_modal($('#app-ad').html());
            return;
        }

        if (c3nav._current_user_location) {
            c3nav._locationinput_set($(this).parent(), c3nav._current_user_location);
            c3nav.update_state();
        }
    },
    _locationinput_reset_autocomplete: function () {
        // hide autocomplete
        const $autocomplete = $('#autocomplete');
        $autocomplete.find('.focus').removeClass('focus');
        $autocomplete.html('');
        c3nav._last_locationinput_words_key = null;
        c3nav.current_locationinput = null;
    },
    _locationinput_blur: function () {
        // when a locationinput is blurred…
        const suggestion = $(this).parent().data('suggestion');
        if (suggestion) {
            // if it has a suggested location in it currently
            c3nav._locationinput_set($(this).parent(), suggestion);
            c3nav.update_state();
        } else {
            // otherwise, forget the last location
            $(this).parent().data('lastlocation', null);
        }
    },
    _locationinput_global_focuschange: function (e) {
        // when focus changed, reset autocomplete if it is outside of locationinputs or autocomplete
        if (c3nav.current_locationinput && !$(e.target).is('#autocomplete *, #' + c3nav.current_locationinput + ' *')) {
            c3nav._locationinput_reset_autocomplete();
        }
        if (c3nav._click_anywhere_popup && !$(e.target).is('.leaflet-popup *')) {
            c3nav._click_anywhere_popup.remove();
        }
        if (!$(e.target).is('#search *')) {
            $('#search').removeClass('focused');
        } else if ($(e.target).is('.locationinput input')) {
            $('#search').addClass('focused');
        }
    },
    _locationinput_keydown: function (e) {
        const $autocomplete = $('#autocomplete');
        if (e.which === 27) {
            // escape: reset the location input
            const origval = $(this).data('origval');
            if (origval) {
                $(this).val(origval).removeData('origval');
                $(this).parent().removeData('suggestion');
                $autocomplete.find('.focus').removeClass('focus');
            } else {
                c3nav._locationinput_reset($(this).parent());
            }
        } else if (e.which === 40 || e.which === 38) {
            // arrows up/down
            const $locations = $autocomplete.find('.location');
            if (!$locations.length) return;

            // save current input value in case we have to restore it
            if (!$(this).data('origval')) {
                $(this).data('origval', $(this).val())
            }

            // find focused element and remove focus
            const $focused = $locations.filter('.focus');
            $locations.removeClass('focus');

            // find next element
            let next;
            if (!$focused.length) {
                next = $locations.filter((e.which === 40) ? ':first-child' : ':last-child');
            } else {
                next = (e.which === 40) ? $focused.next() : $focused.prev();
            }

            if (!next.length) {
                // if there is no next element, restore original value
                $(this).val($(this).data('origval')).parent().removeData('suggestion');
            } else {
                // otherwise, focus this element, and save location to the input
                next.addClass('focus');
                $(this).val(next.find('span').text()).parent()
                    .data('suggestion', c3nav.locations_by_id[next.attr('data-id')]);
            }
        } else if (e.which === 13) {
            // enter: select currently focused suggestion or first suggestion
            let $focused = $autocomplete.find('.location.focus');
            if (!$focused.length) {
                $focused = $autocomplete.find('.location:first-child');
            }
            if (!$focused.length) return;
            c3nav._locationinput_set($(this).parent(), c3nav.locations_by_id[$focused.attr('data-id')]);
            c3nav.update_state();
            c3nav.fly_to_bounds(true);
        }
    },
    _global_keydown: function (e) {
        if (e.originalEvent.key === 'PageUp') {
            c3nav._level_up();
            e.preventDefault();
            e.stopPropagation();
        } else if (e.originalEvent.key === 'PageDown') {
            c3nav._level_down();
            e.preventDefault();
            e.stopPropagation();
        }
    },
    _level_up() {
        let levelIdx = this.levels.findIndex(x => x[0] === c3nav._levelControl.currentLevel);
        if (levelIdx === -1) return;
        levelIdx += 1;
        if (levelIdx >= c3nav.levels.length) return;
        c3nav._levelControl.setLevel(c3nav.levels[levelIdx][0]);
    },
    _level_down() {
        let levelIdx = this.levels.findIndex(x => x[0] === c3nav._levelControl.currentLevel);
        if (levelIdx === -1) return;
        levelIdx -= 1;
        if (levelIdx < 0) return;
        c3nav._levelControl.setLevel(c3nav.levels[levelIdx][0]);
    },
    _locationinput_hover_suggestion: function () {
        $(this).addClass('focus').siblings().removeClass('focus');
    },
    _locationinput_click_suggestion: function () {
        const $locationinput = $('#' + c3nav.current_locationinput);
        const $this = $(this);
        const locationId = $this.attr('data-id');
        if (locationId) {
            c3nav._locationinput_set($locationinput, c3nav.locations_by_id[$(this).attr('data-id')]);
            c3nav.update_state();
            c3nav.fly_to_bounds(true);
        } else {
            const overlayId = $this.attr('data-overlay-id');
            if (overlayId) {
                const featureId = $this.attr('data-feature-id');

                const overlay = c3nav._overlayControl._overlays[overlayId];
                const featureLayer = overlay.feature_layers[featureId];
                const feature = overlay.features_by_id[featureId];
                const bounds = featureLayer.getBounds();
                c3nav.update_map_state(true, feature.level_id, bounds.getCenter(), c3nav.map.getZoom());
                c3nav._locationLayerBounds = {[feature.level_id]: bounds};
                c3nav.fly_to_bounds(true);
                featureLayer.fire('click');

                c3nav._locationinput_clear();
            }
        }

    },
    _locationinput_matches_compare: function (a, b) {
        if (a[1] !== b[1]) return b[1] - a[1];
        if (a[2] !== b[2]) return b[2] - a[2];
        if (a[3] !== b[3]) return b[3] - a[3];
        if (a[4] !== b[4]) return b[4] - a[4];
        return a[5] - b[5];
    },
    _locationinput_input: function () {
        const matches = [];
        const val = $(this).removeData('origval').val();
        const val_trimmed = $.trim(val);
        const val_words = val_trimmed.toLowerCase().split(/\s+/);
        const val_words_key = val_words.join(' ');
        const $autocomplete = $('#autocomplete');
        const $parent = $(this).parent();
        $parent.toggleClass('empty', val === '').removeData('suggestion');
        if ($parent.is('.selected')) {
            $parent.removeClass('selected').data('location', null);
            c3nav.update_state();
        }

        $autocomplete.find('.focus').removeClass('focus');
        c3nav.current_locationinput = $parent.attr('id');

        if (val_trimmed === '') {
            c3nav._locationinput_reset_autocomplete();
            return;
        }
        if (val_words_key === c3nav._last_locationinput_words_key) return;
        c3nav._last_locationinput_words_key = val_words_key;

        for (let i = 0; i < c3nav.locations.length; i++) {
            const location = c3nav.locations[i];
            let leading_words_count = 0;

            // each word has to be in the location
            let nomatch = false;
            for (let j = 0; j < val_words.length; j++) {
                const val_word = val_words[j];
                if (location.match.indexOf(val_word) === -1) {
                    nomatch = true;
                    break;
                }
            }
            if (nomatch) continue;

            // how many words from the beginning are in the title
            for (j = 0; j < val_words.length; j++) {
                const val_word = val_words[j];
                if (location.title_words[j] !== val_word &&
                    (j !== val_words.length - 1 || location.title_words[j].indexOf(val_word) !== 0)) break;
                leading_words_count++;
            }

            // how many words in total can be found
            let words_start_count = 0;
            let words_total_count = 0;
            for (j = 0; j < val_words.length; j++) {
                const val_word = val_words[j];
                if (location.match.indexOf(' ' + val_word + ' ') !== -1) {
                    words_total_count++;
                } else if (location.match.indexOf(' ' + val_word) !== -1) {
                    words_start_count++;
                }
            }

            matches.push([location.elem, leading_words_count, words_total_count, words_start_count, -location.title.length, i])
        }

        for (const overlay of c3nav.activeOverlays()) {
            matches.push(...overlay.search(val_words));
        }


        matches.sort(c3nav._locationinput_matches_compare);

        $autocomplete.html('');
        const max_items = Math.min(matches.length, Math.floor($('#resultswrapper').height() / 55));
        for (let i = 0; i < max_items; i++) {
            $autocomplete.append(matches[i][0]);
        }
    },

    _random_location_click: function () {
        const $button = $('button.random');
        const parent = $button.parent();
        const width = parent.width();
        const height = parent.height();

        const $cover = $('<div>').css({
            'width': width + 'px',
            'height': height + 'px',
            'background-color': 'var(--color-background)',
            'position': 'absolute',
            'top': 0,
            'left': $button.position().left + $button.width() / 2 + 'px',
            'z-index': 200,
        }).appendTo(parent);

        $cover.animate({
            left: 5 + $button.width() / 2 + 'px'
        }, 300, 'swing');
        $button.css({
            'left': $button.position().left,
            'background-color': 'var(--color-background)',
            'right': null,
            'z-index': 201,
            'opacity': 1,
            'transform': 'scale(1)',
            'color': 'var(--color-primary)',
            'pointer-events': 'none'
        }).animate({
            left: 5,
        }, 300, 'swing').queue(function (d) {
            d();
            const possible_locations_set = new Set();
            for (const id of c3nav.random_location_groups) {
                const group = c3nav.locations_by_id[id];
                if (!group) continue;
                if (!group.locationtype || group.locationtype !== 'locationgroup') continue;
                group.locations.forEach(subid => {
                    if (subid in c3nav.locations_by_id) possible_locations_set.add(subid)
                });
            }
            const possible_locations = Array.from(possible_locations_set);
            const location = c3nav.locations_by_id[possible_locations[Math.floor(Math.random() * possible_locations.length)]];
            c3nav._locationinput_set($('#destination-input'), location);
            c3nav.update_state(false);
            c3nav.fly_to_bounds(true);
            $cover.animate({
                left: width + $button.width() / 2 + 'px'
            }, 300, 'swing');
            $button.animate({
                left: width,
            }, 300, 'swing').queue(function (d) {
                d();
                $button.attr('style', 'display: none;');
                $cover.remove();
                // give the css transition some time
            }).delay(300).queue(function (d) {
                d();
                $button.attr('style', '');
            });
        });
    },

    modal_noclose: false,
    open_modal: function (content, no_close) {
        c3nav.modal_noclose = no_close;
        const $modal = $('#modal');
        c3nav._set_modal_content(content, no_close);
        if (!$modal.is('.show')) {
            c3nav._push_state({modal: true, sidebar: true});
            $modal.addClass('show');
        }
    },
    _set_modal_content: function (content, no_close) {
        const $modal = $('#modal');
        const $content = $modal.find('#modal-content-inner');
        $modal.toggleClass('loading', !content);
        $modal.toggleClass('no-close', no_close);
        $content.html(content || '<div class="loader"></div>');
        if ($content.find('[name=look_for_ap]').length) {
            $content.find('button[type=submit]').hide();
            if (!window.mobileclient) {
                $content.find('p, form').remove();
                $content.append('<p>This quest is only available in the android app.</p>'); // TODO translate
            } else {
                c3nav._ap_name_scan_result_update();
            }
        } else if ($content.find('[name=beacon_measurement_quest]').length) {
            $content.find('button[type=submit]').hide();
            if (!window.mobileclient) {
                $content.find('p, form').remove();
                $content.append('<p>This quest is only available in the android app.</p>'); // TODO translate
            } else {
                const $scanner = $('<div class="beacon-quest-scanner"></div>');
                const $button = $('<button class="button">start scanning</button>')
                    .click(() => {
                        $button.remove();
                        $scanner.append('<p>Scanning… Please do not close this popup and do not move.</p>');
                        c3nav._quest_wifi_scans = [];
                        c3nav._beacon_quest_scanning = true;
                    })
                $scanner.append($button);
                $content.find('form').prev().after($scanner)
            }
        }
    },
    _quest_wifi_scans: [],
    _quest_ibeacon_scans: [],
    _wifi_measurement_scan_update: function () {

        const wifi_display_results = [];
        const bluetooth_display_results = [];
        for (const scan of c3nav._quest_wifi_scans) {
            for (const peer of scan) {
                let found = false;
                for (const existing_peer of wifi_display_results) {
                    if (peer.bssid === existing_peer.bssid && peer.ssid === existing_peer.ssid) {
                        existing_peer.rssi = peer.rssi;
                        found = true;
                        break;
                    }
                }
                if (!found) {
                    wifi_display_results.push(peer);
                }
            }
        }
        for (const scan of c3nav._quest_ibeacon_scans) {
            for (const peer of scan) {
                let found = false;
                for (const existing_peer of bluetooth_display_results) {
                    if (peer.uuid === existing_peer.uuid && peer.major === existing_peer.major && peer.minor === existing_peer.minor) {
                        existing_peer.distance = peer.distance;
                        found = true;
                        break;
                    }
                }
                if (!found) {
                    bluetooth_display_results.push(peer);
                }
            }
        }

        const $scanner = $('#modal .beacon-quest-scanner');

        const $wifi_table = $(`<table><tr><td colspan="3"><i>${c3nav._quest_wifi_scans.length} wifi scans</i></td></tr><tr><th>BSSID</th><th>SSID</th><th>RSSI</th></tr></table>`);

        for (const peer of wifi_display_results) {
            $wifi_table.append(`<tr><td>${peer.bssid}</td><td>${peer.ssid}</td><td>${peer.rssi}</td></tr>`);
        }


        const $bluetooth_table = $(`<table><tr><td colspan="3"><i>${c3nav._quest_ibeacon_scans.length} wifi scans</i></td></tr><tr><th>ID</th><th>Distance</th></table>`);

        for (const peer of bluetooth_display_results) {
            $bluetooth_table.append(`<tr><td>${peer.major}</td><td>${peer.minor}</td><td>${peer.distance}</td></tr>`);
        }


        $scanner.empty();
        if (c3nav._quest_wifi_scans.length < 1) {
            $scanner.append('<p>Scanning… Please do not close this popup and do not move.</p>');
        } else {
            $('#modal input[name=data]').val(JSON.stringify({
                wifi: c3nav._quest_wifi_scans,
                ibeacon: c3nav._quest_ibeacon_scans,
            }))
            $('#modal button[type=submit]').show();
        }

        if (wifi_display_results.length > 0) {
            $scanner.append($wifi_table);
        }
        if (bluetooth_display_results.length > 0) {
            $scanner.append($bluetooth_table);
        }

    },

    _ap_name_scan_result_update: function () {
        const $modal = $('#modal');
        const $match_ap = $modal.find('[name=look_for_ap]');
        if ($match_ap.length) {
            const $addresses = $('[name=addresses]');
            const ap_name = $match_ap.val();
            const found_bssids = {};
            let scan_complete = false;
            if (ap_name in c3nav._ap_name_mappings) {
                const mappings = c3nav._ap_name_mappings[ap_name];
                for (const mapping of mappings) {
                    scan_complete = true;
                    for (const bssid of mapping) {
                        found_bssids[bssid] = (found_bssids[bssid] ?? 0) + 1;
                        if (found_bssids[bssid] === 1) {
                            scan_complete = false;
                        }
                    }
                }
            }

            const $table = $('<table class="ap-name-bssid-result"><thead><tr><th>BSSID</th><th>count</th></tr></thead></table>')

            for (const [bssid, count] of Object.entries(found_bssids)) {
                $table.append(`<tr><td>${bssid}</td><td>${count}</td></tr>`);
            }

            $modal.find('.ap-name-bssid-result').remove();

            $modal.find('form').before($table);

            if (scan_complete) {
                // todo only bssids that have count > 1
                $addresses.val(JSON.stringify(Object.keys(found_bssids)));
                $('#modal button[type=submit]').show();
            }
        }
    },
    _modal_click: function (e) {
        if (!c3nav.modal_noclose && (e.target.id === 'modal' || e.target.id === 'close-modal')) {
            history.back();
            if (c3nav._questsControl) c3nav._questsControl.reloadQuests(true);
        }
    },
    _href_modal_open_tab: function (location) {
        return ['/l/', '/control/', '/reports/', '/mesh/', '/api-secrets/', '/editor/'].some(prefix => location.startsWith(prefix));
    },
    _modal_link_click: function (e) {
        const location = $(this).attr('href');
        if ($(this).is('[target]') || c3nav._href_modal_open_tab(location)) {
            if (!$(this).is('[target]')) $(this).attr('target', '_blank');
            return;
        }
        e.preventDefault();
        e.stopPropagation();
        c3nav.open_modal();
        $.get(location, c3nav._modal_loaded).fail(c3nav._modal_error);
    },
    _modal_submit: function (e) {
        e.preventDefault();
        $.ajax({
            url: $(this).attr('action'),
            data: new FormData($(this)[0]),
            cache: false,
            contentType: false,
            processData: false,
            method: 'POST',
            success: c3nav._modal_loaded,
        }).fail(c3nav._modal_error);
        c3nav.open_modal();
    },
    _modal_loaded: function (data) {
        if (data.startsWith('{')) {
            c3nav._set_user_data(JSON.parse(data));
            history.back();
            return;
        }
        const html = $('<div>' + data.replace('<body', '<div') + '</div>');
        const user_data = html.find('[data-user-data]');
        if (user_data.length) {
            c3nav._set_user_data(JSON.parse(user_data.attr('data-user-data')));
        }
        c3nav._set_modal_content(html.find('main').html());
    },
    _modal_error: function (data) {
        console.error(data);
        $('#modal').removeClass('loading').find('#modal-content').html('<h3>Error ' + data.status + '</h3>');
    },

    // map
    init_map: function () {
        const $map = $('#map');
        const $main = $('main');
        c3nav.bounds = JSON.parse($map.attr('data-bounds'));
        c3nav.levels = JSON.parse($map.attr('data-levels'));
        c3nav.tile_server = $map.attr('data-tile-server');

        if ($map.is('[data-initial-bounds]')) {
            const bounds_raw = JSON.parse($map.attr('data-initial-bounds'));
            const bounds = [bounds_raw.slice(0, 2), bounds_raw.slice(2)];
            c3nav.initial_bounds = bounds;
        } else {
            c3nav.initial_bounds = c3nav.bounds
        }

        if ($map.is('[data-initial-level]')) {
            c3nav.initial_level = parseInt($map.attr('data-initial-level'));
        } else if (c3nav.levels.length) {
            c3nav.initial_level = c3nav.levels[0][0];
        } else {
            c3nav.initial_level = 0
        }

        c3nav.level_indices_by_id = {};
        for (let i = 0; i < c3nav.levels.length; i++) {
            c3nav.level_indices_by_id[c3nav.levels[i][0]] = c3nav.levels[i][1];
        }

        const minZoom = Math.log2(Math.max(0.25, Math.min(
            ($main.width() - 40) / (c3nav.bounds[1][0] - c3nav.bounds[0][0]),
            ($main.height() - 250) / (c3nav.bounds[1][1] - c3nav.bounds[0][1])
        )));

        // create leaflet map
        c3nav.map = L.map('map', {
            renderer: L.svg({padding: 2}),
            zoom: 0,
            maxZoom: 6,
            minZoom: minZoom,
            crs: L.CRS.Simple,
            maxBounds: L.GeoJSON.coordsToLatLngs(c3nav._get_padded_max_bounds(minZoom)),
            zoomSnap: 0,
            zoomControl: false,
            attributionControl: !window.mobileclient,
        });
        if (!window.mobileclient) c3nav.map.attributionControl.setPrefix($('#attributions').html());
        if (!('ontouchstart' in window || navigator.maxTouchPoints)) {
            $('.leaflet-touch').removeClass('leaflet-touch');
        }

        c3nav.create_key(c3nav.theme);

        c3nav.map.fitBounds(L.GeoJSON.coordsToLatLngs(c3nav.initial_bounds), c3nav._add_map_padding({}));

        c3nav.map.on('moveend', c3nav._map_moved);
        c3nav.map.on('zoomend', c3nav._map_zoomed);

        // set up icons
        L.Icon.Default.imagePath = '/static/leaflet/images/';
        c3nav.create_icons();

        // setup scale control
        L.control.scale({imperial: false}).addTo(c3nav.map);

        // setup level control
        c3nav._levelControl = new LevelControl({initialTheme: c3nav.theme}).addTo(c3nav.map);
        c3nav._locationLayers = {};
        c3nav._nearbyLayers = {};
        c3nav._locationLayerBounds = {};
        c3nav._detailLayers = {};
        c3nav._routeLayers = {};
        c3nav._routeLayerBounds = {};
        c3nav._userLocationLayers = {};
        c3nav._overlayLayers = {};
        c3nav._questsLayers = {};
        c3nav._positionsLayers = {};
        c3nav._firstRouteLevel = null;
        c3nav._labelLayer = L.LayerGroup.collision({margin: 5}).addTo(c3nav.map);
        c3nav._loadIndicatorLayer = L.LayerGroup.collision({margin: 5}).addTo(c3nav.map);
        for (let i = c3nav.levels.length - 1; i >= 0; i--) {
            const level = c3nav.levels[i];
            const layerGroup = c3nav._levelControl.addLevel(level[0], level[2]);
            c3nav._detailLayers[level[0]] = L.layerGroup().addTo(layerGroup);
            c3nav._locationLayers[level[0]] = L.layerGroup().addTo(layerGroup);
            c3nav._nearbyLayers[level[0]] = L.markerClusterGroup({
                maxClusterRadius: 35,
                spiderLegPolylineOptions: {
                    color: '#4b6c97',
                },
                showCoverageOnHover: false,
                iconCreateFunction: makeClusterIconCreate('#4b6c97'),
            }).addTo(layerGroup);
            c3nav._routeLayers[level[0]] = L.layerGroup().addTo(layerGroup);
            c3nav._userLocationLayers[level[0]] = L.layerGroup().addTo(layerGroup);
            c3nav._overlayLayers[level[0]] = L.layerGroup().addTo(layerGroup);
            c3nav._questsLayers[level[0]] = L.markerClusterGroup({
                spiderLegPolylineOptions: {
                    color: 'var(--color-primary)',
                },
                showCoverageOnHover: false,
                iconCreateFunction: makeClusterIconCreate('var(--color-primary)'),
            }).addTo(layerGroup);
            c3nav._positionsLayers[level[0]] = L.layerGroup().addTo(layerGroup);
        }
        c3nav._levelControl.finalize();
        c3nav._levelControl.setLevel(c3nav.initial_level);

        c3nav._labelControl = new ToggleControl({
            storageId: 'labels',
            initialOn: true,
            enabledIcon: c3nav._map_material_icon('label'),
            disabledIcon: c3nav._map_material_icon('label_off'),
            onEnable: () => {
                c3nav._labelLayer.addTo(c3nav.map);
                c3nav.update_location_labels();
            },
            onDisable: () => {
                c3nav._labelLayer.clearLayers();
                c3nav._labelLayer.remove();
            },
        }).addTo(c3nav.map);

        c3nav._loadIndicatorControl = new ToggleControl({
            storageId: 'load_indicator',
            enabledIcon: c3nav._map_material_icon('bar_chart'),
            disabledIcon: c3nav._map_material_icon('bar_chart_off'),
            onEnable: () => {
                c3nav._update_loadinfo_labels();
            },
            onDisable: () => {
                c3nav._update_loadinfo_labels();
            },
        }).addTo(c3nav.map);

        // setup grid control
        if ($map.is('[data-grid]')) {
            c3nav._gridLayer = new L.SquareGridLayer(JSON.parse($map.attr('data-grid')));
            c3nav._gridControl = new ToggleControl({
                storageId: 'grid',
                initialOn: true,
                enabledIcon: c3nav._map_material_icon('grid_on'),
                disabledIcon: c3nav._map_material_icon('grid_off'),
                onEnable: () => {
                    c3nav._gridLayer.addTo(c3nav.map);
                },
                onDisable: () => {
                    c3nav._gridLayer.remove();
                },
            }).addTo(c3nav.map);
        }
        if (Object.values(c3nav.themes).length > 1) {
            new ThemeControl().addTo(c3nav.map);
        }

        // setup user location control
        if ($main.is('[data-ssids]')) c3nav._userLocationControl = new UserLocationControl().addTo(c3nav.map);

        L.control.zoom({
            position: 'bottomright'
        }).addTo(c3nav.map);

        c3nav._update_overlays();
        c3nav._update_quests();
        c3nav._update_positions();
        c3nav._update_loadinfo_labels();

        c3nav.map.on('click', c3nav._click_anywhere);

        c3nav.schedule_fetch_updates();

    },
    theme: 0,
    setTheme: function (id) {
        if (id === c3nav.theme) return;
        c3nav.theme = id;
        const theme = c3nav.themes[id];
        if (!theme.funky) {
            c3nav_api.post('settings/theme/?id=' + id);
            localStorageWrapper.setItem('c3nav-theme', c3nav.theme); // TODO: instead (or additionally?) do a request to save it in the session!
        }
        document.querySelector('#c3nav-theme-css-vars').innerText = theme.css_vars;
        document.querySelector('#c3nav-theme-css-extra').innerText = theme.css_extra;

        document.querySelector('#theme-color-meta-dark').content = theme.theme_color_dark;
        document.querySelector('#theme-color-meta-light').content = theme.theme_color_light;

        c3nav.create_icons();

        c3nav._levelControl.setTheme(id);
        c3nav.create_key(id);
    },
    show_theme_select: function (e) {
        e.preventDefault();
        c3nav.open_modal(document.querySelector('main>.theme-selection').outerHTML);
        const select = document.querySelector('#modal .theme-selection select');
        for (const id of Object.keys(c3nav.themes).toSorted()) {
            const theme = c3nav.themes[id];
            const option = document.createElement('option');
            option.value = id;
            option.innerText = theme.name;
            select.append(option);
        }
        const currentThemeOption = select.querySelector(`[value="${c3nav.theme}"]`);
        if (currentThemeOption) {
            currentThemeOption.selected = true;
        }
    },
    select_theme: function (e) {
        const themeId = e.target.parentElement.querySelector('select').value;
        c3nav.setTheme(themeId);
        history.back(); // close the modal
    },

    legend_control: null,
    create_key: function (theme_id) {
        c3nav_api.get(`map/legend/${theme_id}/`)
            .then(key => {
                const entries = [...key.base, ...key.groups, ...key.obstacles];
                const legend_control = new LegendControl();
                for (const entry of entries) {
                    legend_control.addKey(entry.title, entry.fill, entry.border);
                }
                if (c3nav.legend_control !== null) {
                    c3nav.map.removeControl(c3nav.legend_control);
                }
                if (entries.length > 0) {
                    c3nav.legend_control = legend_control;
                    legend_control.addTo(c3nav.map);
                }
            });
    },

    _click_anywhere_popup: null,
    _click_anywhere: function (e) {
        if (e.originalEvent.target.id !== 'map') return;
        if (c3nav.embed) return;
        c3nav._click_anywhere_load(false, e.latlng);
    },
    _latlng_to_name: function (latlng) {
        const level = c3nav.current_level();
        return 'c:' + String(c3nav.level_indices_by_id[level]) + ':' + Math.round(latlng.lng * 100) / 100 + ':' + Math.round(latlng.lat * 100) / 100;
    },
    _click_anywhere_load: function (nearby, latlng) {
        if (!c3nav._click_anywhere_popup && !latlng) return;
        if (latlng === undefined) latlng = c3nav._click_anywhere_popup.getLatLng();
        if (c3nav._click_anywhere_popup) c3nav._click_anywhere_popup.remove();
        const popup = L.popup().setLatLng(latlng).setContent('<div class="loader"></div>');
        const name = c3nav._latlng_to_name(latlng);
        c3nav._click_anywhere_popup = popup;
        popup.on('remove', function () {
            c3nav._click_anywhere_popup = null
        }).openOn(c3nav.map);
        c3nav_api.get(`map/locations/${name}/`)
            .then(data => {
                if (c3nav._click_anywhere_popup !== popup || !popup.isOpen()) return;
                popup.remove();
                if (nearby) {
                    const $destination = $('#destination-input');
                    c3nav._locationinput_set($destination, data);
                    c3nav.update_state(false, false, false, false, true);
                } else {
                    const newpopup = L.popup(c3nav._add_map_padding({
                        className: 'location-popup',
                        maxWidth: 500
                    }, 'autoPanPaddingTopLeft', 'autoPanPaddingBottomRight'));
                    const buttons = $('#location-popup-buttons').clone();
                    buttons.find('.report').attr('href', '/report/l/' + String(data.id) + '/');
                    buttons.find('.set-position').attr('href', '/positions/set/' + name + '/');
                    newpopup.setLatLng(latlng).setContent(c3nav._build_location_html(data) + buttons.html());
                    c3nav._click_anywhere_popup = newpopup;
                    newpopup.on('remove', function () {
                        c3nav._click_anywhere_popup = null
                    }).openOn(c3nav.map);
                }
            })
            .catch(function () {
                popup.remove();
            });
    },
    _map_moved: function () {
        c3nav.update_map_state();
        c3nav.update_location_labels();
        c3nav._update_loadinfo_labels();
    },
    _map_zoomed: function () {
        c3nav.update_map_state();
        c3nav.update_location_labels();
        c3nav._update_loadinfo_labels();
    },
    icons: {},
    create_icons: function () {
        const theme = c3nav.themes[c3nav.theme];
        const rootPath = theme.icon_path || '/static/img/';
        const config = (theme.marker_config ? JSON.parse(theme.marker_config) : null) ?? {};

        c3nav.icons = {};
        for (const name of ['default', 'origin', 'destination', 'nearby']) {
            c3nav.icons[name] = new L.Icon({
                iconUrl: rootPath + 'marker-icon-' + name + '.png',
                iconRetinaUrl: rootPath + 'marker-icon-' + name + '-2x.png',
                shadowUrl: rootPath + 'marker-shadow.png',
                iconSize: [25, 41],
                iconAnchor: [12, 41],
                popupAnchor: [1, -34],
                tooltipAnchor: [16, -28],
                shadowSize: [41, 41],
                ...config,
            });
        }

    },
    visible_map_locations: [],
    update_map_locations: function () {
        // update locations markers on the map
        const origin = $('#origin-input').data('location');
        const destination = $('#destination-input').data('location');
        const single = !$('main').is('[data-view^=route]');
        const bounds = {};
        for (const level_id in c3nav._locationLayers) {
            c3nav._locationLayers[level_id].clearLayers()
        }
        for (const level_id in c3nav._nearbyLayers) {
            c3nav._nearbyLayers[level_id].clearLayers()
        }
        c3nav._visible_map_locations = [];
        if (origin) c3nav._merge_bounds(bounds, c3nav._add_location_to_map(origin, single ? c3nav.icons.default : c3nav.icons.origin));
        if (destination) c3nav._merge_bounds(bounds, c3nav._add_location_to_map(destination, single ? c3nav.icons.default : c3nav.icons.destination));
        const done = new Set();
        if (c3nav.state.nearby && destination && 'areas' in destination) {
            if (destination.space) {
                done.add(destination.space);
                c3nav._merge_bounds(bounds, c3nav._add_location_to_map(c3nav.locations_by_id[destination.space], c3nav.icons.nearby, true, c3nav._nearbyLayers));
            }
            if (destination.near_area) {
                done.add(destination.near_area);
                c3nav._merge_bounds(bounds, c3nav._add_location_to_map(c3nav.locations_by_id[destination.near_area], c3nav.icons.nearby, true, c3nav._nearbyLayers));
            }
            for (const area of destination.areas) {
                if (done.has(area)) continue;
                done.add(area);
                c3nav._merge_bounds(bounds, c3nav._add_location_to_map(c3nav.locations_by_id[area], c3nav.icons.nearby, true, c3nav._nearbyLayers));
            }
            for (const location of destination.nearby) {
                if (done.has(location)) continue;
                done.add(destination.nearby);
                c3nav._merge_bounds(bounds, c3nav._add_location_to_map(c3nav.locations_by_id[location], c3nav.icons.nearby, true, c3nav._nearbyLayers));
            }
        }
        c3nav._locationLayerBounds = bounds;
    },
    fly_to_bounds: function (replace_state, nofly) {
        // fly to the bounds of the current overlays
        let level = c3nav.current_level();
        let bounds = null;

        if (c3nav._firstRouteLevel) {
            level = c3nav._firstRouteLevel;
            bounds = c3nav._routeLayerBounds[level];
        } else if (c3nav._locationLayerBounds[level]) {
            bounds = c3nav._locationLayerBounds[level];
        } else {
            for (const level_id in c3nav._locationLayers) {
                if (c3nav._locationLayerBounds[level_id]) {
                    bounds = c3nav._locationLayerBounds[level_id];
                    level = level_id
                }
            }
        }
        c3nav._levelControl.setLevel(level);
        if (bounds) {
            const target = c3nav.map._getBoundsCenterZoom(bounds, c3nav._add_map_padding({}));
            const center = c3nav.map._limitCenter(target.center, target.zoom, c3nav.map.options.maxBounds);
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
        const $search = $('#search');
        const    $main = $('main');
        const padBesideSidebar = (
            $main.width() > 1000 &&
            ($main.height() < 250 || c3nav.state.details || c3nav.state.options)
        );
        const left = padBesideSidebar ? ($search.width() || 0) + 10 : 0;
        const top = padBesideSidebar ? 10 : ($search.height() || 0) + 10;
        if ('maxWidth' in options) {
            options.maxWidth = Math.min(options.maxWidth, $main.width() - left - 13 - 50)
        }
        options[topleft || 'paddingTopLeft'] = L.point(left + 13, top + 41);
        options[bottomright || 'paddingBottomRight'] = L.point(50, 20);
        return options;
    },
    _get_padded_max_bounds: function (zoom) {
        if (zoom === undefined) zoom = c3nav.map.getZoom();
        const bounds = c3nav.bounds;
        const factor = Math.pow(2, zoom);
        return [
            [bounds[0][0] - 600 / factor, bounds[0][1] - 200 / factor],
            [bounds[1][0] + 600 / factor, bounds[1][1] + 200 / factor]
        ];
    },
    _location_point_overrides: {},
    _add_location_to_map: function (location, icon, no_geometry, layers) {
        if (!layers) {
            layers = c3nav._locationLayers;
        }
        if (!location) {
            // if location is not in the searchable list...
            return
        }
        if (location.dynamic || location.locationtype === "dynamiclocation" || location.locationtype === "position") {
            if (!('available' in location)) {
                c3nav_api.get(`map/positions/${location.id}/`)
                    .then(c3nav._dynamic_location_loaded);
                return;
            } else if (!location.available) {
                return;
            }
        }
        // add a location to the map as a marker
        if (location.locations) {
            const bounds = {};
            for (let i = 0; i < location.locations.length; i++) {
                c3nav._merge_bounds(bounds, c3nav._add_location_to_map(c3nav.locations_by_id[location.locations[i]], icon, true));
            }
            return bounds;
        }

        if (!no_geometry && c3nav._visible_map_locations.indexOf(location.id) === -1) {
            c3nav._visible_map_locations.push(location.id);
            c3nav_api.get(`map/locations/${location.id}/geometry/`).then(c3nav._location_geometry_loaded);
        }

        if (!location.point) return;
        const point = c3nav._location_point_overrides[location.id] || location.point.slice(1);
        const latlng = L.GeoJSON.coordsToLatLng(point);
        let buttons_html = '';
        if (!c3nav.embed) {
            let buttons = $('#location-popup-buttons').clone();
            buttons.find('.report').attr('href', '/report/l/' + String(location.id) + '/');
            buttons_html = buttons.html();
        }

        L.marker(latlng, {
            icon: icon
        }).bindPopup(location.elem + buttons_html, c3nav._add_map_padding({
            className: 'location-popup',
            maxWidth: 500
        }, 'autoPanPaddingTopLeft', 'autoPanPaddingBottomRight')).addTo(layers[location.point[0]]);

        const result = {};
        result[location.point[0]] = L.latLngBounds(
            location.bounds ? L.GeoJSON.coordsToLatLngs(location.bounds) : [latlng, latlng]
        );
        return result
    },
    _merge_bounds: function (bounds, new_bounds) {
        for (const level_id in new_bounds) {
            bounds[level_id] = bounds[level_id] ? bounds[level_id].extend(new_bounds[level_id]) : new_bounds[level_id];
        }
    },
    _dynamic_location_loaded: function (data) {
        if (c3nav._maybe_update_dynamic_location($('#origin-input'), data) || c3nav._maybe_update_dynamic_location($('#destination-input'), data)) {
            c3nav.update_state();
            c3nav.fly_to_bounds(true);
        }
    },
    _maybe_update_dynamic_location: function (elem, location) {
        if (elem.is('.empty')) return false;
        const orig_location = elem.data('location');
        if (orig_location.id !== location.id) return false;

        const new_location = $.extend({}, orig_location, location);
        c3nav._locationinput_set(elem, new_location);
        return true;
    },

    _location_geometry_loaded: function (data) {
        if (c3nav._visible_map_locations.indexOf(data.id) === -1 || data.geometry === null || data.level === null) return;

        if (data.geometry.type === "Point") return;
        L.geoJSON(data.geometry, {
            style: {
                color: 'var(--color-map-overlay)',
                fillOpacity: 0.2,
                interactive: false,
            }
        }).addTo(c3nav._locationLayers[data.level]);
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
        c3nav_api.get('updates/fetch')
            .then(c3nav._fetch_updates_callback)
            .catch(err => {
                console.error(err);
                c3nav._fetch_updates_failure_count++;
                const waittime = Math.min(5 + c3nav._fetch_updates_failure_count * 5, 120);
                c3nav.schedule_fetch_updates(waittime * 1000);
            });
    },
    resume_level: null,
    _fetch_updates_callback: function (data) {
        if (c3nav.resume_level !== null) {
            c3nav._levelControl.setLevel(c3nav.resume_level);
            c3nav.resume_level = null;
        }
        c3nav._fetch_updates_failure_count = 0;
        c3nav.schedule_fetch_updates();
        if (c3nav.last_site_update !== data.last_site_update) {
            c3nav.new_site_update = true;
            c3nav.last_site_update = data.last_site_update;
            c3nav._maybe_load_site_update(c3nav.state);
        }
        c3nav._set_user_data(data.user_data);
    },
    _maybe_load_site_update: function (state) {
        if (c3nav.new_site_update && !state.modal && (!state.routing || !state.origin || !state.destination)) {
            c3nav._load_site_update();
        }
    },
    _load_site_update: function () {
        $('#modal-content').css({
            width: 'auto',
            minHeight: 0
        });
        c3nav.open_modal($('#reload-msg').html(), true);
        window.location.reload();
    },
    _set_user_data: function (data) {
        c3nav_api.authenticate();
        c3nav.user_data = data;
        c3nav._update_overlays();
        c3nav._update_quests();
        const $user = $('header #user');
        $user.find('span').text(data.title);
        $user.find('small').text(data.subtitle || '');
        $('.position-buttons').toggle(data.has_positions);
        if (window.mobileclient) mobileclient.setUserData(JSON.stringify(data));
    },
    _current_overlays_key: null,
    _update_overlays: function () {
        if (!c3nav.map) return;

        const key = c3nav.user_data.overlays.map(o => o.id).join(',');
        if (key === c3nav._current_overlays_key) return;
        c3nav._current_overlays_key = key;

        const control = new OverlayControl({levels: c3nav._overlayLayers});
        for (const overlay of c3nav.user_data.overlays) {
            control.addOverlay(new DataOverlay(overlay));
        }

        if (c3nav._overlayControl) {
            c3nav.map.removeControl(c3nav._overlayControl);
        }

        if (c3nav.user_data.overlays.length > 0) {
            c3nav._overlayControl = control.addTo(c3nav.map);
        }
    },

    activeOverlays: function () {
        if (!c3nav._overlayControl) return [];
        return Object.values(c3nav._overlayControl._overlays).filter(o => o.active);
    },

    _update_quests: function () {
        if (!c3nav.map) return;
        if (c3nav._questsControl) {
            if (!Object.keys(c3nav.user_data.quests).length) {
                c3nav.map.removeControl(c3nav._questsControl);
                c3nav._questsControl = null;
            }
        } else {
            if (Object.keys(c3nav.user_data.quests).length) c3nav._questsControl = (new QuestsControl()).addTo(c3nav.map);
        }
    },

    _update_positions: function () {
        if (!c3nav.map) return;
        if (c3nav._positionsControl) {
            if (!c3nav.user_data.has_positions) {
                c3nav.map.removeControl(c3nav._positionsControl);
                c3nav._positionsControl = null;
            }
        } else {
            if (c3nav.user_data.has_positions) c3nav._positionsControl = (new PositionsControl()).addTo(c3nav.map);
        }
    },

    _hasLocationPermission: undefined,
    hasLocationPermission: function (nocache) {
        if (c3nav._hasLocationPermission === undefined || (nocache !== undefined && nocache === true)) {
            if (window.mobileclient) {
                c3nav._hasLocationPermission = typeof window.mobileclient.hasLocationPermission !== 'function' || window.mobileclient.hasLocationPermission();
            } else if (navigator.bluetooth) {
                navigator.bluetooth.getAvailability().then((available) => {
                    if (available) {
                        c3nav._hasLocationPermission = true;
                    } else {
                        c3nav._hasLocationPermission = false;
                    }
                });
            }
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
    getBLEScanRate: function () {
        return 2000;
    },
    _wifiScanningTimer: null,
    startWifiScanning: function () {
        if (c3nav._wifiScanningTimer == null) {
            console.info("started wifi scanning with interval of " + c3nav.getWifiScanRate());
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
    _c3BeaconUuuid: "a142621a-2f42-09b3-245b-e1ac6356e9b0",
    _maxBLEAdvertisements: 128,
    _receivedBLEAdvertisements: [],
    _BLEreportingInterval: null,
    startBLEScanning: function () {
        if (window.mobileclient) {
            if (mobileclient.registerBeaconUuid) {
                mobileclient.registerBeaconUuid(c3nav._c3BeaconUuuid);
            }
        } else if (navigator.bluetooth) {
            if (c3nav._bleScan && c3nav._bleScan.active)
                return;

            navigator.bluetooth.getAvailability().then((available) => {
                if (available && navigator.userActivation.isActive) {
                    c3nav._bleScan = navigator.bluetooth.requestLEScan({
                        keepRepeatedDevices: true,
                        acceptAllAdvertisements: true // iBeacons are non-connectable, can't filter directly
                    });
                    navigator.bluetooth.addEventListener('advertisementreceived', c3nav._handleBLEAdvertisement);
                }
            });
        }
    },
    stopBLEScanning: function () {
        if (c3nav._bleScan && c3nav._bleScan.active)
            c3nav._bleScan.stop();

        if (c3nav._BLEreportingInterval)
            clearInterval(c3nav._BLEreportingInterval);
    },
    _calciBeaconDistance: function (txPower, rssi) {
        if (rssi == 0)
            return -1.0;

        ratio = rssi*1.0/txPower;
        if (ratio < 1.0)
            distance =  Math.pow(ratio,10);
        else
            distance =  (0.89976) * Math.pow(ratio,7.7095) + 0.111;
        
        return distance;
    },
    _bytesToUUID: function (bytes) {
        const hex = bytes.map(b => b.toString(16).padStart(2, "0")).join("");
        return (
            hex.substring(0, 8) + "-" +
            hex.substring(8, 12) + "-" +
            hex.substring(12, 16) + "-" +
            hex.substring(16, 20) + "-" +
            hex.substring(20)
        );
    },
    _handleBLEAdvertisement: function (event) {       
        // Check for Apple Manufacturer Data (0x004C)
        if (!event.manufacturerData || !event.manufacturerData.has(0x004C)) {
            return;
        }

        const beaconData = event.manufacturerData.get(0x004C);

        // iBeacon frames are at least 23 bytes long
        if (beaconData.byteLength < 23) {
            return;
        }
        const beaconView = new DataView(beaconData.buffer);

        // Format of iBeacon manufacturer data:
        // Byte 0-1: Company ID (0x004C)
        // Byte 2: Type (0x02)
        // Byte 3: Length (0x15)
        // Byte 4-19: UUID
        // Byte 20-21: Major
        // Byte 22-23: Minor
        // Byte 24: Tx Power

        // Validate iBeacon prefix (0x02 0x15)
        if (beaconView.getUint8(0) !== 0x02 || beaconView.getUint8(1) !== 0x15) return;

        // Extract UUID
        const uuidBytes = [];
        for (let i = 2; i < 18; i++) uuidBytes.push(beaconView.getUint8(i));

        const _uuid = bytesToUUID(uuidBytes);

        // Not our beacons
        if (_uuid != c3nav._c3BeaconUuuid)
            return;

        const _rssi = event.rssi;
        const _timestamp = event.timeStamp;
        const _major = beaconView.getUint16(18, false);
        const _minor = beaconView.getUint16(20, false);
        const _txPower = -beaconView.getInt8(22);

        const _pathLoss = (_txPower - _rssi);
        const _distance = c3nav._calciBeaconDistance(_txPower, _rssi);
        const _lastSeen = _timestamp;
        var _lastSeenBeacons = c3nav._receivedBLEAdvertisements.filter(obj => {
            return obj.uuid == _uuid
        }).sort(
            (a, b) => b.timestamp - a.timestamp
        );

        if (_lastSeenBeacons.length > 0)
            _lastSeen = _lastSeenBeacons[0].timestamp;

        var beacon = {
            uuid: _uuid,
            major: _major,
            minor: _minor,
            rssi: _rssi,
            txPower: _txPower,
            path_loss: _pathLoss,
            distance: _distance,
            timestamp: _timestamp,
            lastSeen: _lastSeen,
        };
        c3nav._receivedBLEAdvertisements.push(beacon);

        if (!c3nav._BLEreportingInterval) {
            c3nav._BLEreportingInterval = setInterval(function() {
                c3nav._ibeacon_scan_results(c3nav._receivedBLEAdvertisements);
                
                // Housekeeping
                if (c3Nav._receivedBLEAdvertisements.length > 128)
                    c3nav._receivedBLEAdvertisements = c3nav._receivedBLEAdvertisements.slice((-1 * _maxBLEAdvertisements / 2));

                if (c3nav._bleScan && !c3nav._bleScan.active)
                    c3nav.startBLEScanning();
            }, c3nav.getBLEScanRate());
        }
    },
    _last_scan: 0,
    _last_wifi_peers: [],
    _last_ibeacon_peers: [],
    _no_scan_count: 0,
    _ap_name_mappings: {},
    _beacon_quest_scan_results: {},
    _enable_scan_debugging: false,
    _scan_debugging_results: [],
    _wifi_scan_results: function (peers) {
        // important: we need to send peers even if empty, because we get an interesting useful answer from the server
        peers = JSON.parse(peers);

        if (c3nav._enable_scan_debugging) {
            c3nav._scan_debugging_results.push({
                timestamp: Date.now(),
                peers: peers,
            });
        }

        if (c3nav.ssids) {
            peers = peers.filter(peer => c3nav.ssids.includes(peer.ssid));
        }

        const ap_name_mappings = {};

        for (const peer of peers) {
            if (peer.level !== undefined) {
                peer.rssi = peer.level;
                delete peer.level;
            }
            if (peer.rtt) {
                peer.distance = peer.rtt.distance_mm / 1000;
                peer.distance_sd = peer.rtt.distance_std_dev_mm / 1000;
                delete peer.rtt;
            }
            if (peer.ap_name) {
                let mapping = ap_name_mappings[peer.ap_name] =(ap_name_mappings[peer.ap_name] ?? new Set());
                mapping.add(peer.bssid);
            }
        }

        for (const [name, mapping] of Object.entries(ap_name_mappings)) {
            let mappings = c3nav._ap_name_mappings[name] = (c3nav._ap_name_mappings[name] ?? []);
            mappings.push([...mapping]);
        }

        localStorageWrapper.setItem('c3nav.wifi-scanning.ap-names', JSON.stringify(c3nav._ap_name_mappings));

        c3nav._ap_name_scan_result_update();

        if (c3nav._beacon_quest_scanning) {
            c3nav._quest_wifi_scans.push(peers);
            c3nav._wifi_measurement_scan_update();
        }

        c3nav._last_wifi_peers = peers;
        c3nav._after_scan_results();
    },
    _ibeacon_scan_results: function (peers) {
        return;  // disabled causae no ibeacon support currently
        peers = JSON.parse(peers);
        c3nav._last_ibeacon_peers = peers;

        if (c3nav._beacon_quest_scanning) {
            c3nav._quest_ibeacon_scans.push(peers);
            c3nav._wifi_measurement_scan_update();
        }

        c3nav._after_scan_results();
    },
    _after_scan_results: function () {
        const has_peers = c3nav._last_wifi_peers.length || c3nav._last_ibeacon_peers.length;
        if (has_peers) {
            c3nav._hasLocationPermission = true;
        } else {
            c3nav.hasLocationPermission(true);
        }

        const now = Date.now();
        if (now - 4000 < c3nav._last_scan) return;

        if (!has_peers) {
            if (!c3nav._hasLocationPermission) {
                c3nav._set_user_location(null);
            } else {
                if (c3nav._no_scan_count > 5) {
                    c3nav._no_scan_count = 0;
                    c3nav._set_user_location(null);
                } else {
                    c3nav._no_scan_count++;
                }
            }
            // don't abort here, we still need to send the data
        } else {
            c3nav._no_scan_count = 0;
        }

        const ibeacon_peers = c3nav._last_ibeacon_peers.map(p => ({...p}));
        for (const peer of ibeacon_peers) {
            peer.last_seen_ago = Math.max(0, now - peer.last_seen);
        }

        c3nav_api.post('positioning/locate/', {
            wifi_peers: c3nav._last_wifi_peers,
            ibeacon_peers: ibeacon_peers,
        })
            .then(data => {
                c3nav._set_user_location(data.location, data.precision);
                if (typeof mobileclient !== 'undefined' && mobileclient.suggestedWifiPeersReceived) {
                    mobileclient.suggestedWifiPeersReceived(JSON.stringify(data.suggested_peers));
                }
            })
            .catch(err => {
                console.error(err);
                c3nav._set_user_location(null);
                c3nav._last_scan = Date.now() + 20000
            });
    },
    _current_user_location: null,
    _last_user_location_time: 0,
    _set_user_location: function (location, precision, force) {
        const currentLocationRequested = (
            typeof mobileclient !== 'undefined' &&
            mobileclient.isCurrentLocationRequested &&
            mobileclient.isCurrentLocationRequested()
        );
        if (force !== true) force = currentLocationRequested;
        if (location === null) {
            if (force !== true && c3nav._last_user_location_time > Date.now()-60000) {
                // no location, but we had a location less than a minute ago, so we ignore this
                // if force is true the location is set to null even then
                return;
            }
        } else {
            c3nav._last_user_location_time = Date.now();
        }
        c3nav._current_user_location = location;
        for (const id in c3nav._userLocationLayers) {
            c3nav._userLocationLayers[id].clearLayers();
        }
        if (location) {
            $('.locationinput .locate, .leaflet-control-user-location a').text(c3nav._map_material_icon('my_location'));
            $('.locationinput .locate, .leaflet-control-user-location a').show();
            const latlng = L.GeoJSON.coordsToLatLng(location.geometry.coordinates);
            for (const level in c3nav._userLocationLayers) {
                if (!c3nav._userLocationLayers.hasOwnProperty(level)) continue;
                const layer = c3nav._userLocationLayers[level];
                const factor = (parseInt(level) === location.level) ? 1 : 0.3;
                if (precision !== undefined && precision !== null) {
                    L.circle(latlng, {
                        radius: precision,
                        stroke: 0,
                        fillOpacity: 0.1
                    }).addTo(layer);
                } else {
                    L.circleMarker(latlng, {
                        radius: 11,
                        stroke: 0,
                        fillOpacity: 0.1
                    }).addTo(layer);
                }
                L.circleMarker(latlng, {
                    radius: 5,
                    stroke: 0,
                    fillOpacity: 1 * factor
                }).addTo(layer);
            }
            $('.leaflet-control-user-location a').toggleClass('control-disabled', false);
        } else if (c3nav.hasLocationPermission()) {
            $('.locationinput .locate, .leaflet-control-user-location a').text(c3nav._map_material_icon('location_searching'));
            $('.locationinput .locate, .leaflet-control-user-location a').show();
            $('.leaflet-control-user-location a').toggleClass('control-disabled', false);
        } else {
            $('.locationinput .locate, .leaflet-control-user-location a').text(c3nav._map_material_icon('location_disabled'));
            $('.leaflet-control-user-location a').toggleClass('control-disabled', true);
        }
        if (typeof mobileclient !== 'undefined' && mobileclient.isCurrentLocationRequested && mobileclient.isCurrentLocationRequested()) {
            if (location) {
                c3nav._goto_user_location_click();
            } else {
                mobileclient.currentLocationRequesteFailed()
            }
        }
    },
    _goto_user_location_click: function (e) {
        e.preventDefault();
        if (!window.mobileclient) {
            c3nav.open_modal($('#app-ad').html());
            return;
        }
        if (typeof window.mobileclient.checkLocationPermission === 'function') {
            window.mobileclient.checkLocationPermission(true);
        }
        if (c3nav._current_user_location) {
            c3nav._levelControl.setLevel(c3nav._current_user_location.level);
            c3nav.map.flyTo(L.GeoJSON.coordsToLatLng(c3nav._current_user_location.geometry.coordinates), 3, {duration: 1});
        }
    },

    _material_symbols_codepoints: null,
    load_material_symbols_if_needed: function () {
        // load material icons codepoint for android 4.3.3 and other heccing old browsers
        const elem = document.createElement('span');
        const before = elem.style.fontFeatureSettings;
        let ligaturesSupported = false;
        if (before !== undefined) {
            elem.style.fontFeatureSettings = '"liga" 1';
            ligaturesSupported = (elem.style.fontFeatureSettings !== before);
        }
        if (!ligaturesSupported) {
            $.get('/static/material-symbols/MaterialSymbolsOutlined.codepoints', c3nav._material_symbols_loaded);
        }
    },
    _material_symbols_loaded: function (data) {
        const lines = data.split("\n");
        const result = {};

        for (let i = 0; i < lines.length; i++) {
            const line = lines[i].split(' ');
            if (line.length === 2) {
                result[line[0]] = String.fromCharCode(parseInt(line[1], 16));
            }
        }
        c3nav._material_symbols_codepoints = result;
        $('.material-symbols').each(function () {
            $(this).text(c3nav._map_material_icon($(this).text()));
        });
    },
    _map_material_icon: function (name) {
        if (c3nav._material_symbols_codepoints === null) return name;
        return c3nav._material_symbols_codepoints[name] || '';
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
        if (c3nav._levelControl) {
            c3nav.resume_level = c3nav._levelControl.currentLevel;
            c3nav._levelControl.setLevel(null);
        }

        if (c3nav._overlayControl) {
            c3nav._overlayControl.pause();
        }

        c3nav.stopBLEScanning();
    },
    _resume: function () {
        if (c3nav._fetch_updates_timer === null) {
            console.info("c3nav._resume() -> fetch_updates");
            c3nav.fetch_updates();
        }
        if (c3nav._searchable_locations_timer === null) {
            let scheduled_load_in = null
            if (c3nav._last_time_searchable_locations_loaded !== null) {
                scheduled_load_in = c3nav._last_time_searchable_locations_loaded + c3nav._searchable_locations_interval - Date.now();
            }
            if (scheduled_load_in === null || scheduled_load_in <= 5000) {
                c3nav.load_searchable_locations();
                console.info("c3nav._resume() -> loading searchable locations");
            } else {
                c3nav._searchable_locations_timer = window.setTimeout(c3nav.load_searchable_locations, scheduled_load_in);
                console.info("c3nav._resume() -> scheduling searchable locations timeout: " + scheduled_load_in);
            }
        }

        if (c3nav._overlayControl) {
            c3nav._overlayControl.resume();
        }

        c3nav.startBLEScanning();
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
$(document).ready(() => {
    c3nav.init();
});

function nearby_stations_available() {
    c3nav._wifi_scan_results(mobileclient.getNearbyStations());
}

function ibeacon_results_available() {
    c3nav._ibeacon_scan_results(mobileclient.getNearbyBeacons());
}

function openInModal(location) {
    c3nav.open_modal();
    $.get(location, c3nav._modal_loaded).fail(c3nav._modal_error);
}

function mobileclientOnPause() {
    c3nav.stopWifiScanning();
    c3nav._pause();
}

function mobileclientOnResume() {
    c3nav.startWifiScanning();
    c3nav._resume();
}

ExpandingControl = L.Control.extend({
    options: {
        storageKey: null,
        pinIcon: 'push_pin',
        icon: '',
    },

    getStored: function(key, fallback=null) {
        if (this.options.storageKey !== null) {
            const fullKey = `c3nav.control.${this.options.storageKey}.${key}`;
            try {
                const value = localStorageWrapper.getItem(fullKey);
                if (value === null) {
                    return fallback;
                }
                return JSON.parse(value);
            } catch (err) {
                console.warn(err);
                localStorageWrapper.removeKey(fullKey);
                return fallback;
            }
        } else {
            return fallback;
        }
    },

    setStored: function(key, value) {
        if (this.options.storageKey !== null) {
            const fullKey = `c3nav.control.${this.options.storageKey}.${key}`;
            localStorageWrapper.setItem(fullKey, JSON.stringify(value));
        }
    },

    onAdd: function () {
        this._pinned = this.getStored('pinned', false);

        this._container = L.DomUtil.create('div', 'leaflet-control-expanding ' + this.options.addClasses);
        this._content = L.DomUtil.create('div', 'leaflet-control-expanding-content', this._container);
        this._pin = L.DomUtil.create('div', 'pin-toggle material-symbols', this._container);
        this._pin.innerText = c3nav._map_material_icon(this.options.pinIcon);
        this._collapsed = L.DomUtil.create('a', 'collapsed-toggle', this._container);
        this._collapsed.textContent = c3nav._map_material_icon(this.options.icon);
        this._collapsed.href = '#';

        if (!L.Browser.android) {
            L.DomEvent.on(this._container, {
                mouseenter: this.expand,
                mouseleave: this.collapse
            }, this);
        }

        if (L.Browser.mobile) {
            this._pinned = false;
        }

        if (L.Browser.touch) {
            $(this._collapsed).click((e) => {
                e.preventDefault();
                e.stopPropagation();
                this.expand();
            });
            $(this._map).on('click', (e) => {
                this.collapse();
            });
        } else {
            L.DomEvent.on(this._container, 'focus', this.expand, this);
            L.DomEvent.on(this._container, 'blur', this.collapse, this);
        }

        this._expanded = this._pinned;
        this._container.classList.toggle('leaflet-control-expanded', this._expanded);
        this._pin.classList.toggle('active', this._pinned);

        $(this._container).on('click', 'div.pin-toggle', e => {
            this.togglePinned();
        });
        $(this._container).on('click dblclick mousedown pointerdown wheel', e => {
            e.stopPropagation();
        });

        this.refresh();

        return this._container;
    },

    refresh: function () {
        this.render(this._content);
    },

    expand: function () {
        if (this._pinned) return;
        this._expanded = true;
        this._container.classList.add('leaflet-control-expanded');
        return this;
    },

    collapse: function () {
        if (this._pinned) return;
        this._expanded = false;
        this._container.classList.remove('leaflet-control-expanded');
        return this;
    },

    togglePinned: function () {
        this._pinned = !this._pinned;
        if (this._pinned) {
            this._expanded = true;
        }
        this._pin.classList.toggle('active', this._pinned);
        this.setStored('pinned', this._pinned);
    },

    render: function (content) {},
});


LevelControl = L.Control.extend({
    options: {
        position: 'bottomright',
        addClasses: '',
        initialTheme: 0,
    },

    onAdd: function () {
        this._container = L.DomUtil.create('div', 'leaflet-control-levels leaflet-bar ' + this.options.addClasses);
        this._tileLayers = {};
        this._overlayLayers = {};
        this._levelButtons = {};
        this.currentLevel = null;
        this.currentTheme = this.options.initialTheme;
        return this._container;
    },

    createTileLayer: function (id) {
        const urlPattern = (c3nav.tile_server || '/map/') + `${id}/{z}/{x}/{y}/${this.currentTheme}.webp`;
        return L.tileLayer(urlPattern, {
            minZoom: -2,
            maxNativeZoom: 5,
            bounds: L.GeoJSON.coordsToLatLngs(c3nav.bounds)
        });
    },
    setTheme: function (theme) {
        if (theme === this.currentTheme) return;
        this.currentTheme = theme;
        if (this.currentLevel !== null) {
            this._tileLayers[this.currentLevel].remove();
        }

        for (const id in this._tileLayers) {
            this._tileLayers[id] = this.createTileLayer(id);
        }

        if (this.currentLevel !== null) {
            this._tileLayers[this.currentLevel].addTo(c3nav.map);
        }
    },
    addLevel: function (id, title) {
        this._tileLayers[id] = this.createTileLayer(id);
        const overlay = L.layerGroup();
        this._overlayLayers[id] = overlay;

        const link = L.DomUtil.create('a', '', this._container);
        link.innerHTML = title;
        link.level = id;
        link.href = '#';

        L.DomEvent
            .on(link, 'mousedown dblclick', L.DomEvent.stopPropagation)
            .on(link, 'click', this._levelClick, this);

        this._levelButtons[id] = link;
        return overlay;
    },
    setLevel: function (id) {
        if (id === this.currentLevel) return true;
        if (id !== null && this._tileLayers[id] === undefined) return false;

        if (this.currentLevel !== null) {
            this._tileLayers[this.currentLevel].remove();
            this._overlayLayers[this.currentLevel].remove();
            L.DomUtil.removeClass(this._levelButtons[this.currentLevel], 'current');
        }
        if (id !== null) {
            this._tileLayers[id].addTo(c3nav.map);
            this._overlayLayers[id].addTo(c3nav.map);
            L.DomUtil.addClass(this._levelButtons[id], 'current');
        }
        this.currentLevel = id;
        return true;
    },

    _levelClick: function (e) {
        e.preventDefault();
        e.stopPropagation();
        this.setLevel(e.target.level);
        c3nav.update_map_state();
        c3nav.update_location_labels();
        c3nav._update_loadinfo_labels();
    },

    finalize: function () {
        const buttons = $(this._container).find('a');
        buttons.addClass('current');
        buttons.width(buttons.width());
        buttons.removeClass('current');
    },

    reloadMap: function () { // TODO: create fresh tile layers
        if (this.currentLevel === null) return;
        const old_tile_layer = this._tileLayers[this.currentLevel];
        const new_tile_layer = this.createTileLayer(this.currentLevel);
        this._tileLayers[this.currentLevel] = new_tile_layer;
        new_tile_layer.addTo(c3nav.map);
        window.setTimeout(function () {
            old_tile_layer.remove();
        }, 2000);
    }
});

UserLocationControl = L.Control.extend({
    options: {
        position: 'bottomright',
        addClasses: ''
    },

    onAdd: function () {
        this._container = L.DomUtil.create('div', 'leaflet-control-user-location leaflet-bar ' + this.options.addClasses);
        this._button = L.DomUtil.create('a', 'material-symbols', this._container);
        this._button.innerHTML = c3nav._map_material_icon(c3nav.hasLocationPermission() ? 'location_searching' : 'location_disabled');
        this._button.classList.toggle('control-disabled', !c3nav.hasLocationPermission());
        this._button.href = '#';
        this.currentLevel = null;
        return this._container;
    }
});

ToggleControl = L.Control.extend({
    options: {
        position: 'bottomright',
        addClasses: '',
        initialOn: false,
        storageId: null,
        enabledIcon: null,
        disabledIcon: null,
        onEnable: null,
        onDisable: null,
    },

    onAdd: function () {
        this.toggle = this.toggle.bind(this);
        this.toggleOn = this.toggleOn.bind(this);
        this.toggleOff = this.toggleOff.bind(this);

        this._container = L.DomUtil.create('div', 'leaflet-control-toggle leaflet-bar ' + this.options.addClasses);
        this._button = L.DomUtil.create('a', 'material-symbols', this._container);
        $(this._button).click(this.toggle).dblclick(function (e) {
            e.stopPropagation();
        });
        this._button.innerText = this.options.enabledIcon;
        this._button.href = '#';
        this._button.classList.toggle('control-disabled', false);

        let initialOn = this.options.initialOn;
        if (this.options.storageId) {
            const onValue = localStorageWrapper.getItem(`c3nav.toggle-control.${this.options.storageId}.on`);
            if (onValue === '1') {
                initialOn = true;
            } else if (onValue === '0') {
                initialOn = false;
            }
        }

        window.setTimeout(() => {
            if (initialOn) {
                this.toggleOn();
            } else {
                this.toggleOff();
            }
        }, 1);

        return this._container;
    },


    toggle: function (e) {
        if (e) e.preventDefault();
        if (this.enabled) {
            this.toggleOff();
        } else {
            this.toggleOn();
        }
    },

    toggleOn: function () {
        if (this.enabled === true) return;
        this.enabled = true;
        if (this.options.onEnable) {
            this.options.onEnable();
        }
        this._button.innerText = this.options.enabledIcon;
        this._button.classList.toggle('control-disabled', false);
        localStorageWrapper.setItem(`c3nav.toggle-control.${this.options.storageId}.on`, '1');
    },

    toggleOff: function () {
        if (this.enabled === false) return;
        this.enabled = false;
        if (this.options.onDisable) {
            this.options.onDisable();
        }
        this._button.innerText = this.options.disabledIcon;
        this._button.classList.toggle('control-disabled', true);
        localStorageWrapper.setItem(`c3nav.toggle-control.${this.options.storageId}.on`, '0');
    }
});

ThemeControl = L.Control.extend({
    options: {
        position: 'bottomright',
        addClasses: '',
    },
    onAdd: function () {
        this._container = L.DomUtil.create('div', 'leaflet-control-theme leaflet-bar ' + this.options.addClasses);
        this._button = L.DomUtil.create('a', 'material-symbols', this._container);
        $(this._button).click(c3nav.show_theme_select).dblclick(function (e) {
            e.stopPropagation();
        });
        this._button.innerText = c3nav._map_material_icon('contrast');
        this._button.href = '#';
        return this._container;
    },
})

QuestsControl = ExpandingControl.extend({
    options: {
        position: 'topright',
        addClasses: 'leaflet-control-quests',
        icon: 'editor_choice',
        storageKey: 'quests',
    },

    _questData: {},

    onAdd: function () {
        this._activeQuests = new Set(this.getStored('active', []));
        for (const name of this._activeQuests) {
            if (!(name in c3nav.user_data.quests)) {
                this._activeQuests.delete(name);
            }
        }
        this._loadedQuests = new Set();

        ExpandingControl.prototype.onAdd.call(this);

        this.reloadQuests().catch(err => console.error(err));

        $(this._container).on('change', 'input[type=checkbox]', e => {
            const questName = e.target.dataset.quest;
            if (e.target.checked) {
                this.showQuest(questName);
            } else {
                this.hideQuest(questName);
            }
        });

        return this._container;
    },

    render: function (container) {
        if (!container) return;
        const fragment = document.createDocumentFragment();
        const title = document.createElement('h4');
        title.textContent = 'Quests';

        fragment.append(title);

        for (const quest_name in c3nav.user_data.quests) {
            const quest = c3nav.user_data.quests[quest_name];

            const label = document.createElement('label');
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.dataset.quest = quest_name;

            if (this._activeQuests.has(quest_name)) {
                checkbox.checked = true;
            }
            label.append(checkbox, quest.label);
            
            fragment.append(label);
        }
        container.replaceChildren(...fragment.children);
    },

    showQuest: function (name) {
        if (this._activeQuests.has(name)) return;
        this._activeQuests.add(name);
        this.setStored('active', [...this._activeQuests]);
        this.reloadQuests().catch(err => console.error(err));
    },

    hideQuest: function (name) {
        if (!this._activeQuests.has(name)) return;
        this._activeQuests.delete(name);
        this.setStored('active', [...this._activeQuests]);
        this.reloadQuests().catch(err => console.error(err));
    },

    reloadQuests: async function (force = false) {
        const activeQuests = this._activeQuests;
        const removed = this._loadedQuests.difference(activeQuests);
        const added = force ? activeQuests : activeQuests.difference(this._loadedQuests);

        if (removed.size === 0 && added.size === 0) return;

        const questData = this._questData;

        for (const name of removed) {
            delete questData[name];
        }

        if (added.size > 0) {
            for(const name of added) {
                questData[name] = [];
            }

            const added_param = [...added].join(',');
            const data = await c3nav_api.get(`map/quests/?quest_type=${added_param}`);
            for (const quest of data) {
                questData[quest.quest_type].push(quest);
            }
        }

        this._questData = questData;
        this._loadedQuests = new Set([...activeQuests]);

        for (const level_id in c3nav._questsLayers) {
            c3nav._questsLayers[level_id].clearLayers();
        }

        for (const quest_type in this._questData) {
            const quests = this._questData[quest_type];
            const quest_icon = c3nav._map_material_icon(c3nav.user_data.quests[quest_type].icon ?? 'editor_choice');

            for (const quest of quests) {
                L.geoJson(quest.point, {
                    pointToLayer: (geom, latlng) => {
                        const span = document.createElement('span');
                        span.innerText = quest_icon;
                        return L.marker(latlng, {
                            icon: L.divIcon({
                                className: 'symbol-icon symbol-icon-interactive',
                                html: span,
                                iconSize: [24, 24],
                                iconAnchor: [12, 12],
                            })
                        });
                    }
                })
                    .addTo(c3nav._questsLayers[quest.level_id])
                    .on('click', function () {
                        c3nav.open_modal();
                        $.get(`/editor/quests/${quest_type}/${quest.identifier}/`, c3nav._modal_loaded).fail(c3nav._modal_error);
                    });
            }


        }
    },
});

PositionsControl = ToggleControl.extend({
    options: {
        position: 'topright',
        addClasses: 'leaflet-control-positions',
        enabledIcon: c3nav._map_material_icon('location_on'),
        disabledIcon: c3nav._map_material_icon('location_off'),
        storageId: 'positions',
        onEnable: () => {
            c3nav._positionsControl.reloadPositions().catch(err => console.error(err));
        },
    },

    reloadPositions: async function () {
        console.log("abc");
        for (const level_id in c3nav._positionsLayers) {
            c3nav._positionsLayers[level_id].clearLayers();
        }

        const data = await c3nav_api.get(`map/positions/my/`);

        for (const position of data) {
            if (!position.available) continue;
            L.geoJson(position.geometry, {
                pointToLayer: (geom, latlng) => {
                    const span = document.createElement('span');
                    span.innerText = position.short_name;
                    return L.marker(latlng, {
                        icon: L.divIcon({
                            className: 'text-icon symbol-icon-interactive',
                            html: span,
                            iconSize: [24, 24],
                            iconAnchor: [12, 12],
                        })
                    });
                }
            })
                .addTo(c3nav._positionsLayers[position.level])
                .bindPopup(() => {
                    const span = document.createElement('span');
                    span.innerText = position.name;
                    return span;
                }, {
                    className: 'data-overlay-popup'
                })
        }
    },
});

LegendControl = ExpandingControl.extend({
    options: {
        position: 'topright',
        addClasses: 'leaflet-control-key',
        icon: 'legend_toggle',
        storageKey: 'legend',
    },
    _keys: [],

    addKey: function (name, background, border) {
        this._keys.push({
            name,
            background,
            border,
        });
        this.refresh();
    },

    render: function (container) {
        if (!container) return;
        const fragment = document.createDocumentFragment();
        for (const key of this._keys) {
            const key_container = document.createElement('div');
            key_container.classList.add('key');
            const color = document.createElement('div');
            color.classList.add('key-color');
            if (key.background !== null) {
                color.style.backgroundColor = key.background;
            }
            if (key.border !== null) {
                color.style.borderColor = key.border;
            }

            const name = document.createElement('div');
            name.innerText = key.name;
            key_container.append(color, name);
            fragment.append(key_container);
        }
        container.replaceChildren(...fragment.children);
    },
});

OverlayControl = ExpandingControl.extend({
    options: {
        position: 'topright',
        addClasses: 'leaflet-control-overlays',
        icon: 'stacks',
        storageKey: 'overlays',
        levels: {}
    },

    _overlays: {},
    _ungrouped: [],
    _groups: {},

    initialize: function ({levels, ...config}) {
        this.config = config;
        this._levels = levels;
    },

    pause: function () {
        for (const overlay of Object.values(this._overlays)) {
            overlay.pause();
        }
    },

    resume: function () {
        for (const overlay of Object.values(this._overlays)) {
            overlay.resume();
        }
    },

    onAdd: function () {

        const initialActiveOverlays = this.getStored('active', []);
        const initialCollapsedGroups = this.getStored('collapsed', []);

        for (const overlay of initialActiveOverlays) {
            if (overlay in this._overlays) {
                this._overlays[overlay].visible = true;
                this._overlays[overlay].enable(this._levels);
            }
        }

        for (const group of initialCollapsedGroups) {
            if (group in this._groups) {
                this._groups[group].expanded = false;
            }
        }

        ExpandingControl.prototype.onAdd.call(this);

        this.refresh();

        $(this._container).on('change', 'input[type=checkbox]', e => {
            this._overlays[e.target.dataset.id].visible = e.target.checked;
            this.updateOverlay(e.target.dataset.id);
        });
        $(this._container).on('click', '.content h4', e => {
            this.toggleGroup(e.target.parentElement.dataset.group);
        });
        return this._container;
    },

    addOverlay: function (overlay) {
        this._overlays[overlay.id] = overlay;
        if (overlay.group == null) {
            this._ungrouped.push(overlay);
        } else {
            if (overlay.group in this._groups) {
                this._groups[overlay.group].overlays.push(overlay);
            } else {
                this._groups[overlay.group] = {
                    expanded: this._initialCollapsedGroups === null || !this._initialCollapsedGroups.includes(overlay.group),
                    overlays: [overlay],
                };
            }
        }

        this.refresh();
    },

    updateOverlay: function (id) {
        const overlay = this._overlays[id];
        if (overlay.visible) {
            overlay.enable(this._levels);
        } else {
            overlay.disable(this._levels);
        }
        const activeOverlays = Object.keys(this._overlays).filter(k => this._overlays[k].visible);
        this.setStored('active', activeOverlays);
    },

    render: function (container) {
        if (!container) return;

        const ungrouped = document.createDocumentFragment();
        const groups = document.createDocumentFragment();

        const render_overlays = (overlays, container) => {
            for (const overlay of overlays) {
                const label = document.createElement('label');
                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.dataset.id = overlay.id;
                if (overlay.visible) {
                    checkbox.checked = true;
                }
                label.append(checkbox, overlay.title);
                container.append(label);
            }
        };

        render_overlays(this._ungrouped, ungrouped);

        for (const group in this._groups) {
            const group_container = document.createElement('div');
            group_container.classList.add('overlay-group');
            if (this._groups[group].expanded) {
                group_container.classList.add('expanded');
            }
            this._groups[group].el = group_container;
            group_container.dataset.group = group;
            const title = document.createElement('h4');
            title.innerText = group;
            group_container.append(title);
            render_overlays(this._groups[group].overlays, group_container);
            groups.append(group_container);
        }
        container.replaceChildren(...ungrouped.children, ...groups.children);
    },

    toggleGroup: function (name) {
        const group = this._groups[name];
        group.expanded = !group.expanded;
        group.el.classList.toggle('expanded', group.expanded);
        const collapsedGroups = Object.keys(this._groups).filter(k => !this._groups[k].expanded);
        this.setStored('collapsed', collapsedGroups);
    },
});

var SvgIcon = L.Icon.extend({
    options: {
        // @section
        // @aka DivIcon options
        iconSize: [12, 12], // also can be set through CSS

        // iconAnchor: (Point),
        // popupAnchor: (Point),

        // @option html: String|SVGElement = ''
        // Custom HTML code to put inside the div element, empty by default. Alternatively,
        // an instance of `SVGElement`.
        iconSvg: null,
        shadowSvg: null,

        // @option bgPos: Point = [0, 0]
        // Optional relative position of the background, in pixels
        bgPos: null,

        className: 'leaflet-svg-icon'
    },

    // @method createIcon(oldIcon?: HTMLElement): HTMLElement
    // Called internally when the icon has to be shown, returns a `<img>` HTML element
    // styled according to the options.
    createIcon: function (oldIcon) {
        return this._createIcon('icon', oldIcon);
    },

    // @method createShadow(oldIcon?: HTMLElement): HTMLElement
    // As `createIcon`, but for the shadow beneath it.
    createShadow: function (oldIcon) {
        return this._createIcon('shadow', oldIcon);
    },

    _createIcon: function (name, oldIcon) {
        const src = this.options[`${name}Svg`];

        if (!src) {
            if (name === 'icon') {
                throw new Error('iconSvg not set in Icon options (see the docs).');
            }
            return null;
        }

        let svgEl;
        if (src instanceof SVGElement) {
            svgEl = src;
        } else {
            svgEl = (new DOMParser()).parseFromString(src, 'image/svg+xml').documentElement;
        }

        this._setIconStyles(svgEl, name);

        return svgEl;
    },
});


L.SquareGridLayer = L.Layer.extend({
    initialize: function (config) {
        this.config = config;
    },

    onAdd: function (map) {
        this._container = L.DomUtil.create('div', 'leaflet-pane c3nav-grid');
        this.getPane().appendChild(this._container);

        this.cols = [];
        this.rows = [];

        for (let i = 0; i < this.config.cols.length; i++) {
            const elem = L.DomUtil.create('div', 'c3nav-grid-column');
            const label = String.fromCharCode(65 + (this.config.invert_x ? (this.config.cols.length - i - 2) : i));
            if (i < this.config.cols.length - 1) {
                elem.innerHTML = '<span>' + label + '</span><span>' + label + '</span>';
            }
            this._container.appendChild(elem);
            this.cols.push(elem);
        }
        for (let i = 0; i < this.config.rows.length; i++) {
            const elem = L.DomUtil.create('div', 'c3nav-grid-row');
            const label = (this.config.invert_y ? (this.config.rows.length - i) : i);
            if (i > 0) {
                elem.innerHTML = '<span>' + label + '</span><span>' + label + '</span>';
            }
            this._container.appendChild(elem);
            this.rows.push(elem);
        }

        this._updateGrid(map);

        map.on('viewreset zoom move zoomend moveend', this._update, this);
    },

    onRemove: function (map) {
        L.DomUtil.remove(this._container);
        this.cols = [];
        this.rows = [];
        map.off('viewreset zoom move zoomend moveend', this._update, this);
    },

    _update: function (e) {
        this._updateGrid(e.target);
    },

    _updateGrid: function (map) {
        if (!this.cols || this.cols.length === 0) return;
        const mapSize = map.getSize();
        const panePos = map._getMapPanePos();
        const sidebarStart = $('#sidebar').outerWidth() + 15;
        const searchHeight = $('#search').outerHeight() + 10;
        const controlsWidth = $('.leaflet-control-zoom').outerWidth() + 10;
        const attributionStart = mapSize.x - $('.leaflet-control-attribution').outerWidth() - 16;
        const bottomRightStart = mapSize.y - $('.leaflet-bottom.leaflet-right').outerHeight() - 24;
        let lastCoord = null;
        this._container.style.width = mapSize.x + 'px';
        this._container.style.height = mapSize.y + 'px';
        this._container.style.left = (-panePos.x) + 'px';
        this._container.style.top = (-panePos.y) + 'px';
        for (let i = 0; i < this.config.cols.length; i++) {
            let coord = map.latLngToContainerPoint([0, this.config.cols[i]], map.getZoom()).x;
            coord = Math.min(mapSize.x, Math.max(-1, coord));
            this.cols[i].style.left = coord + 'px';
            if (i > 0) {
                const size = coord - lastCoord;
                const center = (lastCoord + coord) / 2;
                if (size > 0) {
                    this.cols[i - 1].style.display = '';
                    this.cols[i - 1].style.width = size + 'px';
                    this.cols[i - 1].style.paddingTop = Math.max(0, Math.min(searchHeight, (sidebarStart - center) / 15 * searchHeight)) + 'px';
                    this.cols[i - 1].style.paddingBottom = Math.max(0, Math.min(16, (center - attributionStart))) + 'px';
                } else {
                    this.cols[i - 1].style.display = 'none';
                }
            }
            lastCoord = coord;
        }
        for (let i = 0; i < this.config.rows.length; i++) {
            let coord = map.latLngToContainerPoint([this.config.rows[i], 0], map.getZoom()).y;
            coord = Math.min(mapSize.y, Math.max(-1, coord));
            this.rows[i].style.top = coord + 'px';
            if (i > 0) {
                const size = lastCoord - coord;
                const center = (lastCoord + coord) / 2;
                if (size > 0) {
                    this.rows[i].style.display = '';
                    this.rows[i].style.height = size + 'px';
                    this.rows[i].style.paddingRight = Math.max(0, Math.min(controlsWidth, (center - bottomRightStart) / 16 * controlsWidth)) + 'px';
                } else {
                    this.rows[i].style.display = 'none';
                }
            }
            lastCoord = coord;
        }
    }
});


class DataOverlay {
    levels = null;
    features = [];
    features_by_id = {};
    feature_layers = {};
    feature_geometries = {};
    fetch_timeout = null;
    etag = null;
    active = false;

    constructor(options) {
        this.id = options.id;
        this.title = options.title;
        this.group = options.group;
        this.cluster_points = options.cluster_points;
        this.default_stroke_color = options.stroke_color;
        this.default_stroke_width = options.stroke_width;
        this.default_stroke_opacity = options.stroke_opacity;
        this.default_fill_color = options.fill_color;
        this.default_fill_opacity = options.fill_opacity;
        this.update_interval = options.update_interval === null ? null : options.update_interval * 1000;
    }

    async create() {
        const [
            {data: features, etag},
            feature_geometries
        ] = await Promise.all([
            c3nav_api.get_with_etag(`mapdata/dataoverlayfeatures/?overlay=${this.id}`, null),
            c3nav_api.get(`mapdata/dataoverlayfeaturegeometries/?overlay=${this.id}`)
        ]);
        this.etag = etag;
        this.features = features;

        this.feature_geometries = Object.fromEntries(feature_geometries.map(f => [f.id, f.geometry]));

        this.update_features(features);

        if (this.update_interval !== null && this.fetch_timeout === null) {
            this.fetch_timeout = window.setTimeout(() => {
                this.fetch_features()
                    .catch(err => console.error(err))
            }, this.update_interval);
        }
    }

    pause() {
        if (this.fetch_timeout !== null) {
            window.clearTimeout(this.fetch_timeout);
            this.fetch_timeout = null;
        }
    }

    resume() {
        if (this.active && this.update_interval !== null) {
            // noinspection JSIgnoredPromiseFromCall
            this.fetch_features();
        }
    }

    async fetch_features() {
        if (this.fetch_timeout !== null) {
            window.clearTimeout(this.fetch_timeout);
            this.fetch_timeout = null;
        }
        try {
            const {data: features, etag} = await c3nav_api.get_with_etag(`mapdata/dataoverlayfeatures/?overlay=${this.id}`, this.etag);

            if (features !== null) {
                this.update_features(features);
                this.etag = etag;
            }
        } catch (err) {
            console.error(err);
        }

        if (this.update_interval !== null && this.fetch_timeout === null) {
            this.fetch_timeout = window.setTimeout(() => {
                this.fetch_features()
                    .catch(err => console.error(err))
            }, this.update_interval);
        }
    }

    update_features (features) {
        if (this.levels === null) {
            this.levels = {};
        }

        for (let id in this.levels) {
            this.levels[id].clearLayers();
        }

        this.feature_layers = {};
        this.features_by_id = {};

        for (const feature of features) {
            this.features_by_id[feature.id] = feature;
            const geometry = this.feature_geometries[feature.id]
            const level_id = feature.level_id;
            if (!(level_id in this.levels)) {
                if (this.cluster_points) {
                    this.levels[level_id] = L.markerClusterGroup({
                        spiderLegPolylineOptions: {
                            color: this.default_stroke_color ?? 'var(--color-map-overlay)',
                        },
                        polygonOptions: {
                            color: this.default_stroke_color ?? 'var(--color-map-overlay)',
                            fillColor: this.default_fill_color ?? 'var(--color-map-overlay)',
                        },
                        iconCreateFunction: makeClusterIconCreate(this.default_fill_color ?? 'var(--color-map-overlay)'),
                    });
                } else {
                    this.levels[level_id] = L.layerGroup();
                }
            }
            const style = {
                'color': feature.stroke_color ?? this.default_stroke_color ?? 'var(--color-map-overlay)',
                'weight': feature.stroke_width ?? this.default_stroke_width ?? 1,
                'opacity': feature.stroke_opacity ?? this.default_stroke_opacity ?? 1,
                'fillColor': feature.fill_color ?? this.default_fill_color ?? 'var(--color-map-overlay)',
                'fillOpacity': feature.fill_opacity ?? this.default_fill_opacity ?? 0.2,
            };
            const layer = L.geoJson(geometry, {
                style,
                interactive: feature.interactive,
                pointToLayer: (geom, latlng) => {
                    const span = document.createElement('span');
                    span.style.setProperty('--icon-color', style.color);
                    span.innerText = feature.point_icon ?? '';

                    return L.marker(latlng, {
                        title: feature.title,
                        icon: L.divIcon({
                            className: 'symbol-icon ' + (feature.point_icon ? '' : 'symbol-icon-empty ') + (feature.interactive ? 'symbol-icon-interactive' : ''),
                            html: span,
                            iconSize: [24, 24],
                            iconAnchor: [12, 12],
                        })
                    });
                },
                onEachFeature: (f, layer) => {
                    if (feature.interactive) {
                        layer.bindPopup(() => {
                            const f = document.createDocumentFragment();
                            const h4 = document.createElement('h4');
                            h4.innerText = feature.title;
                            f.append(h4);
                            if (feature.external_url != null) {
                                const a = document.createElement('a');
                                a.href = feature.external_url;
                                a.target = '_blank';
                                a.innerText = 'open external link';
                                f.append(a);
                            }
                            if (feature.extra_data != null) {
                                const table = document.createElement('table');
                                for (const key in feature.extra_data) {
                                    const tr = document.createElement('tr');
                                    const th = document.createElement('th');
                                    th.innerText = key;
                                    const td = document.createElement('td');
                                    td.innerText = feature.extra_data[key];
                                    tr.append(th, td);
                                    table.append(tr);
                                }
                                f.append(table);
                            }
                            return f;
                        }, {
                            className: 'data-overlay-popup'
                        });
                    }
                }
            });

            this.feature_layers[feature.id] = layer;

            this.levels[level_id].addLayer(layer);
        }
    }

    async enable(levels) {
        if (!this.levels) {
            await this.create();
        } else {
            this.fetch_features()
                .catch(err => console.error(err));
        }
        for (const id in levels) {
            if (id in this.levels) {
                levels[id].addLayer(this.levels[id]);
            }
        }
        this.active = true;
    }

    disable(levels) {
        this.active = false;
        for (const id in levels) {
            if (id in this.levels) {
                levels[id].removeLayer(this.levels[id]);
            }
        }
        window.clearTimeout(this.fetch_timeout);
        this.fetch_timeout = null;
    }

    search(words) {
        const feature_matches = (feature, word) => {
            if (feature.title.toLowerCase().includes(word)) return true;
            for (const lang in feature.titles) {
                if (feature.titles[lang].toLowerCase().includes(word)) return true;
            }
            for (const key in feature.extra_data) {
                if (`${feature.extra_data[key]}`.toLowerCase().includes(word)) return true;
            }
            return false;
        }

        const matches = [];

        for (const feature of this.features) {
            let nomatch = false;
            for (const word of words) {
                if (this.title.toLowerCase().includes(word)) continue;

                if (!feature_matches(feature, word)) {
                    nomatch = true;
                }
            }
            if (nomatch) continue;

             const html = $('<div class="location">')
                .append($('<i class="icon material-symbols">').text(c3nav._map_material_icon(feature.point_icon ?? 'place')))
                .append($('<span>').text(feature.title))
                .append($('<small>').text(`${this.title} (Overlay)`))
                 .attr('data-overlay-id', this.id)
                 .attr('data-feature-id', feature.id);
            html.attr('data-location', JSON.stringify(location));

            matches.push([html[0].outerHTML, 0, 0, 0, -feature.title.length, 0])
        }

        return matches;
    }
}