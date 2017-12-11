(function () {
    /*
     * Workaround for 1px lines appearing in some browsers due to fractional transforms
     * and resulting anti-aliasing.
     * https://github.com/Leaflet/Leaflet/issues/3575
     */
    var originalInitTile = L.GridLayer.prototype._initTile;
    L.GridLayer.include({
        _initTile: function (tile) {
            originalInitTile.call(this, tile);

            var tileSize = this.getTileSize();

            tile.style.width = tileSize.x + 1 + 'px';
            tile.style.height = tileSize.y + 1 + 'px';
        }
    });

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
}());

c3nav = {
    init: function () {
        $.getJSON('/api/locations/?searchable', function (data) {
            for (var i = 0; i < data.length; i++) {
                var location = data[i];
                location.elem = c3nav._build_location_html(location);
                location.title_words = location.title.toLowerCase().split(/\s+/);
                location.match = ' ' + location.title_words.join(' ') + ' ';
                c3nav.locations.push(location);
                c3nav.locations_by_id[location.id] = location;
            }
            c3nav.continue_init();
        });

        $('#messages').find('ul.messages li').each(function() {
            $(this).prepend(
                $('<a href="#" class="close"><i class="material-icons">close</i></a>').click(function(e) {
                    e.preventDefault();
                    $(this).parent().remove();
                })
            );
        })
    },
    continue_init: function() {
        c3nav.init_map();

        $('.locationinput').data('location', null);

        var $main = $('main'),
            state = JSON.parse($main.attr('data-state'));
        c3nav.embed = $main.is('[data-embed]');

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
        }

        c3nav.init_locationinputs();

        var $location_buttons = $('#location-buttons');
        $location_buttons.find('.details').on('click', c3nav._location_buttons_details_click);
        $location_buttons.find('.route').on('click', c3nav._location_buttons_route_click);

        $('#location-buttons, #route-result-buttons').find('.share').on('click', c3nav._buttons_share_click);
        $('#route-search-buttons, #route-result-buttons').find('.swap').on('click', c3nav._route_buttons_swap_click);
        $('#route-search-buttons').find('.close').on('click', c3nav._route_buttons_close_click);
        $('#map').on('click', '.location-popup .button-clear', c3nav._popup_button_click);

        $('#modal').on('click', c3nav._modal_click)
            .on('click', 'a', c3nav._modal_link_click)
            .on('submit', 'form', c3nav._modal_submit);
        $('header #user').on('click', c3nav._modal_link_click);

        $('header h1 a').removeAttr('href');

        window.onpopstate = c3nav._onpopstate;
    },
    get_csrf_token: function() {
        return document.cookie.match(new RegExp('c3nav_csrftoken=([^;]+)'))[1];
    },

    state: {},
    update_state: function(routing, replace, details) {
        if (typeof routing !== "boolean") routing = c3nav.state.routing;

        var destination = $('#destination-input').data('location'),
            origin = $('#origin-input').data('location'),
            new_state = {
                routing: routing,
                origin: origin,
                destination: destination,
                sidebar: true,
                details: !!details
            };

        c3nav._push_state(new_state, replace);

        c3nav._sidebar_state_updated(new_state);
    },
    update_map_state: function (replace, level, center, zoom) {
        var new_state = {
            level: center ? level : c3nav._levelControl.currentLevel,
            center: L.GeoJSON.latLngToCoords(center ? center : c3nav.map.getCenter(), 2),
            zoom: Math.round((center ? zoom : c3nav.map.getZoom()) * 100) / 100
        };
        if (!replace) new_state.sidebar = false;

        c3nav._push_state(new_state, replace);
    },
    _sidebar_state_updated: function (state, nofly) {
        var view;
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
        }

        if (view === 'route-result') {
            if (state.route_result) {
                c3nav._display_route_result(state.route_result, nofly);
            } else {
                c3nav.load_route(state.origin, state.destination, nofly);
            }
        } else {
            $('#route-summary').removeAttr('data-origin').removeAttr('data-destination');
            c3nav._clear_route_layers();
        }

        $('main').attr('data-view', view).toggleClass('show-details', state.details);

        var $search = $('#search');
        $search.removeClass('loading');

        var $selected_locationinputs = $('.locationinput.selected');
        $selected_locationinputs.filter(':focus').blur();
        $('#destination-input, [data-view^=route] #origin-input').filter(':not(.selected)').find('input').first().focus();
        if (!$selected_locationinputs.filter(':focus').length) {
            $search.removeClass('focused');
        }

        c3nav.update_map_locations();
    },
    _clear_route_layers: function() {
        c3nav._firstRouteLevel = null;
        c3nav._routeLayerBounds = {};
        for (var id in c3nav._routeLayers) {
            c3nav._routeLayers[id].clearLayers();
        }
    },

    load_location_details: function (location) {
        var $location_details = $('#location-details');
        if ($location_details.attr('data-id') !== String(location.id)) {
            $location_details.addClass('loading').attr('data-id', location.id);
            $.getJSON('/api/locations/'+location.id+'/display', c3nav._location_details_loaded);
        }
    },
    _location_details_loaded: function(data) {
        var $location_details = $('#location-details');
        if ($location_details.attr('data-id') !== String(data.id)) {
            // loaded too late, information no longer needed
            return;
        }
        var line, sublocations, loc, loclist, elem = $('<dl>');
        for (var i = 0; i < data.display.length; i++) {
            line = data.display[i];
            elem.append($('<dt>').text(line[0]));
            if (typeof line[1] === 'string') {
                elem.append($('<dd>').text(line[1]));
            } else if (line[1] === null) {
                elem.append($('<dd>').text('-'));
            } else {
                sublocations = (line[1].length === undefined) ? [line[1]] : line[1];
                loclist = $('<dd>');
                for (var j = 0; j < sublocations.length; j++) {
                    loc = sublocations[j];
                    if (loc.can_search) {
                        loclist.append($('<a>').attr('href', '/l/' + loc.slug + '/details/').attr('data-id', loc.id).click(function (e) {
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
        var $editor = $location_details.find('.editor');
        if (data.editor_url) {
            $editor.attr('href', data.editor_url).show();
        } else {
            $editor.hide();
        }
        $location_details.removeClass('loading');
    },
    load_route: function (origin, destination, nofly) {
        var $route = $('#route-summary');
        if ($route.attr('data-origin') !== String(origin.id) || $route.attr('data-destination') !== String(destination.id)) {
            c3nav._clear_route_layers();
            $route.addClass('loading').attr('data-origin', origin.id).attr('data-destination', destination.id);
            $.post('/api/routing/route/', {
                'origin': origin.id,
                'destination': destination.id,
                'csrfmiddlewaretoken': c3nav.get_csrf_token()
            }, function(data) { c3nav._route_loaded(data, nofly) }, 'json');
        }
    },
    _route_loaded: function(data, nofly) {
        var $route = $('#route-summary');
        if (data.error && $route.is('.loading')) {
            $route.find('span').text(data.error);
            $route.removeClass('loading');
            return;
        }
        if ($route.attr('data-origin') !== String(data.request.origin) || $route.attr('data-destination') !== String(data.request.destination)) {
            // loaded too late, information no longer needed
            return;
        }
        c3nav._push_state({route_result: data.result}, true);
        c3nav._display_route_result(data.result, nofly);
    },
    _display_route_result: function(result, nofly) {
        var $route = $('#route-summary'),
            first_primary_level = null,
            last_primary_level = null,
            level_collect = [],
            next_level_collect = [],
            in_intermediate_level = true,
            item, coords;
        c3nav._clear_route_layers();
        for (var i=0; i < result.items.length; i++) {
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
                        console.log('add to primary (to primary)');
                        c3nav._add_line_to_route(last_primary_level, level_collect.slice(0, -1));
                    } else {
                        console.log('add to primary (to secondary)');
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
                        console.log('add blargh');
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
        c3nav._add_line_to_route(first_primary_level, c3nav._add_intermediate_point(
            result.origin.point.slice(1),
            result.items[0].coordinates.slice(0, 2),
            result.items[1].coordinates.slice(0, 2)
        ), true);
        c3nav._add_line_to_route(last_primary_level, c3nav._add_intermediate_point(
            result.destination.point.slice(1),
            result.items[result.items.length-1].coordinates.slice(0, 2),
            result.items[result.items.length-2].coordinates.slice(0, 2)
        ).reverse(), true);

        c3nav._firstRouteLevel = first_primary_level;
        $route.find('span').text(String(result.distance)+' m');
        $route.removeClass('loading');
        if (!nofly) c3nav.fly_to_bounds(true);
    },
    _add_intermediate_point: function(origin, destination, next) {
        var angle = Math.atan2(destination[1]-next[1], destination[0]-next[0]),
            distance = Math.sqrt(Math.pow(origin[0]-destination[0], 2) + Math.pow(origin[1]-destination[1], 2)),
            offset = Math.min(1.5, distance/4),
            point = [destination[0]+Math.cos(angle)*offset, destination[1]+Math.sin(angle)*offset];
        return [origin, point, destination];
    },
    _add_line_to_route: function(level, coords, gray, link_to_level) {
        if (coords.length < 2) return;
        var latlngs = L.GeoJSON.coordsToLatLngs(c3nav._smooth_line(coords)),
            routeLayer = c3nav._routeLayers[level];
            line = L.polyline(latlngs, {
                color: gray ? '#888888': $('button.swap').css('color'),
                dashArray: (gray || link_to_level) ? '7' : null,
                interactive: false
            }).addTo(routeLayer),
            bounds = {};
        bounds[level] = line.getBounds();

        c3nav._merge_bounds(c3nav._routeLayerBounds, bounds);

        if (link_to_level) {
            L.polyline(latlngs, {
                opacity: 0,
                weight: 15,
                interactive: true
            }).addTo(routeLayer).on('click', function() {
                c3nav._levelControl.setLevel(link_to_level);
            });
        }
    },
    _smooth_line: function(coords) {
        if (coords.length > 2) {
            for (var i=0; i<4; i++) {
                coords = c3nav._smooth_line_iteration(coords);
            }
        }
        return coords
    },
    _smooth_line_iteration: function(coords) {
        // Chaikin'S Corner Cutting Algorithm
        var new_coords = [coords[0]];
        for (var i=1; i<coords.length-1; i++) {
            new_coords.push([(coords[i][0]*5+coords[i-1][0])/6, (coords[i][1]*5+coords[i-1][1])/6]);
            new_coords.push([(coords[i][0]*5+coords[i+1][0])/6, (coords[i][1]*5+coords[i+1][1])/6]);
        }
        new_coords.push(coords[coords.length-1]);
        return new_coords
    },
    _equal_states: function (a, b) {
        if (a.modal !== b.modal) return false;
        if (a.routing !== b.routing || a.details !== b.details) return false;
        if ((a.origin && a.origin.id) !== (b.origin && b.origin.id)) return false;
        if ((a.destination && a.destination.id) !== (b.destination && b.destination.id)) return false;
        if (a.level !== b.level || a.zoom !== b.zoom) return false;
        if (a.center[0] !== b.center[0] || a.center[1] !== b.center[1]) return false;
        return true;
    },
    _build_state_url: function (state, embed) {
        var url = embed ? '/embed' : '';
        if (state.routing) {
            if (state.origin) {
                url += (state.destination) ? '/r/'+state.origin.slug+'/'+state.destination.slug+'/' : '/o/'+state.origin.slug+'/';
            } else {
                url += (state.destination) ? '/d/'+state.destination.slug+'/' : '/r/';
            }
        } else {
            url += state.destination?('/l/'+state.destination.slug+'/'):'/';
        }
        if (state.details && (url.startsWith('/l/') || url.startsWith('/r/'))) {
            url += 'details/'
        }
        if (state.center) {
            url += '@'+String(c3nav.level_labels_by_id[state.level])+','+String(state.center[0])+','+String(state.center[1])+','+String(state.zoom);
        }
        return url
    },
    _push_state: function (state, replace) {
        state = $.extend({}, c3nav.state, state);
        var old_state = c3nav.state;

        if (!replace && c3nav._equal_states(old_state, state)) return;

        var url = c3nav._build_state_url(state, c3nav.embed),
            embed_logo = $('#embed-logo');

        if (embed_logo.length) {
            embed_logo.attr('href', c3nav._build_state_url(state));
        }

        c3nav.state = state;
        if (replace || (!state.sidebar && !old_state.sidebar)) {
            // console.log('state replaced');
            history.replaceState(state, '', url);
        } else {
            // console.log('state pushed');
            history.pushState(state, '', url);
        }
    },
    _onpopstate: function (e) {
        // console.log('state popped');
        c3nav.load_state(e.state);
    },
    load_state: function (state, nofly) {
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
            var center = c3nav.map._limitCenter(L.GeoJSON.coordsToLatLng(state.center), state.zoom, c3nav.map.options.maxBounds);
            if (nofly) {
                c3nav.map.setView(center, state.zoom, {animate: false});
            } else {
                c3nav.map.flyTo(center, state.zoom, {duration: 1});
            }
        }
        $.extend(c3nav.state, state);
    },

    // button handlers
    _location_buttons_details_click: function () {
        c3nav.update_state(null, null, !c3nav.state.details);
    },
    _location_buttons_route_click: function () {
        c3nav.update_state(true);
    },
    _route_buttons_swap_click: function () {
        var $origin = $('#origin-input'),
            $destination = $('#destination-input'),
            tmp = $origin.data('location');
        c3nav._locationinput_set($origin, $destination.data('location'));
        c3nav._locationinput_set($destination, tmp);
        var offset = $destination.position().top-$origin.position().top;
        $origin.stop().css('top', offset).animate({top: 0}, 150);
        $destination.stop().css('top', -offset).animate({top: 0}, 150);
        c3nav.update_state();
    },
    _route_buttons_close_click: function () {
        var $origin = $('#origin-input'),
            $destination = $('#destination-input');
        if ($origin.is('.selected') && !$destination.is('.selected')) {
            c3nav._locationinput_set($destination, $origin.data('location'));
        }
        c3nav.update_state(false);
    },
    _popup_button_click: function () {
        var $location = $(this).siblings('.location'),
            location = $location.is('[data-location]') ? JSON.parse($location.attr('data-location')) : c3nav.locations_by_id[parseInt($location.attr('data-id'))],
            $origin = $('#origin-input'),
            $destination = $('#destination-input');
        if ($(this).is('.as-location')) {
            c3nav._locationinput_set($destination, location);
            c3nav.update_state(false);
        } else {
            var $locationinput = $(this).is('.as-origin') ? $origin : $destination,
                $other_locationinput = $(this).is('.as-origin') ? $destination : $origin,
                other_location = $other_locationinput.data('location');
            c3nav._locationinput_set($locationinput, location);
            if (other_location && (other_location.id === location.id || (other_location.locations && other_location.locations.includes(location.id)))) {
                c3nav._locationinput_set($other_locationinput, null);
            }
            c3nav.update_state(true);
        }
    },

    // share logic
    _buttons_share_click: function () {
        c3nav.open_modal($('main > .share-ui')[0].outerHTML);
        c3nav._update_share_ui();
    },
    _update_share_ui: function(with_position) {
        var $share = $('#modal .share-ui'),
            state = $.extend({}, c3nav.state),
            url;
        if (!with_position) {
            state.center = null;
        }
        url = c3nav._build_state_url(state);
        $share.find('img').attr('src', '/qr'+url);
        $share.find('input').val(window.location.protocol+'//'+window.location.host+url)[0].select();
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
        $('#autocomplete').on('mouseover', '.location', c3nav._locationinput_hover_suggestion)
            .on('click', '.location', c3nav._locationinput_click_suggestion);
        $('html').on('focus', '*', c3nav._locationinput_global_focuschange)
            .on('mousedown', '*', c3nav._locationinput_global_focuschange);
    },
    _build_location_html: function(location, add_data) {
        html = $('<div class="location">')
            .append($('<i class="icon material-icons">').text('place'))
            .append($('<span>').text(location.title))
            .append($('<small>').text(location.subtitle)).attr('data-id', location.id);
        if (add_data) html.attr('data-location', JSON.stringify(location));
        return html[0].outerHTML;
    },
    _locationinput_set: function (elem, location) {
        // set a location input
        if (location && location.elem === undefined) location.elem = c3nav._build_location_html(location);
        c3nav._locationinput_reset_autocomplete();
        elem.toggleClass('selected', !!location).toggleClass('empty', !location)
            .data('location', location).data('lastlocation', location).removeData('suggestion');
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
    _locationinput_reset_autocomplete: function () {
        // hide autocomplete
        var $autocomplete = $('#autocomplete');
        $autocomplete.find('.focus').removeClass('focus');
        $autocomplete.html('');
        c3nav._last_locationinput_words_key = null;
        c3nav.current_locationinput = null;
    },
    _locationinput_blur: function () {
        // when a locationinput is blurred…
        var suggestion = $(this).parent().data('suggestion');
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
        if (c3nav._click_anywhere_popup && !$(e.target).is('.leaflet-popup > *')) {
            c3nav._click_anywhere_popup.remove();
        }
        if (!$(e.target).is('#search *')) {
            $('#search').removeClass('focused');
        } else if ($(e.target).is('.locationinput input')) {
            $('#search').addClass('focused');
        }
    },
    _locationinput_keydown: function (e) {
        var $autocomplete = $('#autocomplete'), $focused, origval;
        if (e.which === 27) {
            // escape: reset the location input
            origval = $(this).data('origval');
            if (origval) {
                $(this).val(origval).removeData('origval');
                $(this).parent().removeData('suggestion');
                $autocomplete.find('.focus').removeClass('focus');
            } else {
                c3nav._locationinput_reset($(this).parent());
            }
        } else if (e.which === 40 || e.which === 38) {
            // arrows up/down
            var $locations = $autocomplete.find('.location');
            if (!$locations.length) return;

            // save current input value in case we have to restore it
            if (!$(this).data('origval')) {
                $(this).data('origval', $(this).val())
            }

            // find focused element and remove focus
            $focused = $locations.filter('.focus');
            $locations.removeClass('focus');

            // find next element
            var next;
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
            $focused = $autocomplete.find('.location.focus');
            if (!$focused.length) {
                $focused = $autocomplete.find('.location:first-child');
            }
            if (!$focused.length) return;
            c3nav._locationinput_set($(this).parent(), c3nav.locations_by_id[$focused.attr('data-id')]);
            c3nav.update_state();
            c3nav.fly_to_bounds(true);
        }
    },
    _locationinput_hover_suggestion: function () {
        $(this).addClass('focus').siblings().removeClass('focus');
    },
    _locationinput_click_suggestion: function () {
        var $locationinput = $('#' + c3nav.current_locationinput);
        c3nav._locationinput_set($locationinput, c3nav.locations_by_id[$(this).attr('data-id')]);
        c3nav.update_state();
        c3nav.fly_to_bounds(true);
    },
    _locationinput_matches_compare: function (a, b) {
        if (a[1] !== b[1]) return b[1] - a[1];
        if (a[2] !== b[2]) return b[2] - a[2];
        if (a[3] !== b[3]) return b[3] - a[3];
        return a[4] - b[4];
    },
    _locationinput_input: function () {
        var matches = [],
            val = $(this).removeData('origval').val(),
            val_trimmed = $.trim(val),
            val_words = val_trimmed.toLowerCase().split(/\s+/),
            val_words_key = val_words.join(' '),
            $autocomplete = $('#autocomplete'),
            $parent = $(this).parent();
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

        for (var i = 0; i < c3nav.locations.length; i++) {
            var location = c3nav.locations[i],
                leading_words_count = 0,
                words_total_count = 0,
                words_start_count = 0,
                nomatch = false,
                val_word, j;

            // each word has to be in the location
            for (j = 0; j < val_words.length; j++) {
                val_word = val_words[j];
                if (location.match.indexOf(val_word) === -1) {
                    nomatch = true;
                    break;
                }
            }
            if (nomatch) continue;

            // how many words from the beginning are in the title
            for (j = 0; j < val_words.length; j++) {
                val_word = val_words[0];
                if (location.title_words[j] !== val_word &&
                    (j !== val_words.length - 1 || location.title_words[j].indexOf(val_word) !== 0)) break;
                leading_words_count++;
            }

            // how many words in total can be found
            for (j = 0; j < val_words.length; j++) {
                val_word = val_words[0];
                if (location.match.indexOf(' ' + val_word + ' ') !== -1) {
                    words_total_count++;
                } else if (location.match.indexOf(' ' + val_word) !== -1) {
                    words_start_count++;
                }
            }

            matches.push([location.elem, leading_words_count, words_total_count, words_start_count, i])
        }

        matches.sort(c3nav._locationinput_matches_compare);

        $autocomplete.html('');
        var max_items = Math.min(matches.length, Math.floor($('#resultswrapper').height() / 55));
        for (i = 0; i < max_items; i++) {
            $autocomplete.append(matches[i][0]);
        }
    },

    open_modal: function (content) {
        var $modal = $('#modal');
        c3nav._set_modal_content(content);
        if (!$modal.is('.show')) {
            c3nav._push_state({modal: true, sidebar: true});
            $modal.addClass('show');
        }
    },
    _set_modal_content: function(content) {
        $('#modal').toggleClass('loading', !content)
            .find('#modal-content')
            .html('<button class="button-clear material-icons" id="close-modal">clear</button>')
            .append(content || '');
    },
    _modal_click: function(e) {
        if (e.target.id === 'modal' || e.target.id === 'close-modal') {
            history.back();
        }
    },
    _modal_link_click: function(e) {
        var location = $(this).attr('href');
        if (location.startsWith('/control/')) {
            $(this).attr('target', '_blank');
            return;
        }
        e.preventDefault();
        e.stopPropagation();
        c3nav.open_modal();
        $.get(location, c3nav._modal_loaded).fail(c3nav._modal_error);
    },
    _modal_submit: function(e) {
        e.preventDefault();
        $.post($(this).attr('action'), $(this).serialize(), c3nav._modal_loaded).fail(c3nav._modal_error);
    },
    _modal_loaded: function(data) {
        if (data.startsWith('{')) {
            c3nav._set_user_data(JSON.parse(data));
            history.back();
            return;
        }
        c3nav._set_modal_content($('<div>'+data+'</div>').find('main').html());
    },
    _modal_error: function(data) {
        $('#modal').removeClass('loading').find('#modal-content').html('<h3>Error '+data.status+'</h3>');
    },

    // map
    init_map: function () {
        var $map = $('#map'),
            $main = $('main'),
            i;
        c3nav.bounds = JSON.parse($map.attr('data-bounds'));
        c3nav.levels = JSON.parse($map.attr('data-levels'));
        c3nav.tile_server = $map.attr('data-tile-server');

        c3nav.level_labels_by_id = {};
        for (i = 0; i < c3nav.levels.length; i ++) {
            c3nav.level_labels_by_id[c3nav.levels[i][0]] = c3nav.levels[i][1];
        }

        minZoom = Math.log2(Math.max(0.25, Math.min(
            ($main.width()-40)/(c3nav.bounds[1][0]-c3nav.bounds[0][0]),
            ($main.height()-250)/(c3nav.bounds[1][1]-c3nav.bounds[0][1])
        )));

        // create leaflet map
        c3nav.map = L.map('map', {
            renderer: L.svg({padding: 2}),
            zoom: 0,
            maxZoom: 5,
            minZoom: minZoom,
            crs: L.CRS.Simple,
            maxBounds: L.GeoJSON.coordsToLatLngs(c3nav._get_padded_max_bounds(minZoom)),
            zoomSnap: 0,
            zoomControl: false
        });
        c3nav.map.attributionControl.setPrefix($('#attributions').html());
        if (L.Browser.chrome && !('ontouchstart' in window)) {
            $('.leaflet-touch').removeClass('leaflet-touch');
        }

        c3nav.map.fitBounds(L.GeoJSON.coordsToLatLngs(c3nav.bounds), c3nav._add_map_padding({}));

        c3nav.map.on('moveend', c3nav._map_moved);
        c3nav.map.on('zoomend', c3nav._map_zoomed);

        // set up icons
        L.Icon.Default.imagePath = '/static/leaflet/images/';
        c3nav._add_icon('origin');
        c3nav._add_icon('destination');

        // setup scale control
        L.control.scale({imperial: false}).addTo(c3nav.map);

        // setup level control
        c3nav._levelControl = new LevelControl().addTo(c3nav.map);
        c3nav._locationLayers = {};
        c3nav._locationLayerBounds = {};
        c3nav._routeLayers = {};
        c3nav._routeLayerBounds = {};
        c3nav._firstRouteLevel = null;
        for (i = c3nav.levels.length - 1; i >= 0; i--) {
            var level = c3nav.levels[i];
            var layerGroup = c3nav._levelControl.addLevel(level[0], level[1]);
            c3nav._locationLayers[level[0]] = L.layerGroup().addTo(layerGroup);
            c3nav._routeLayers[level[0]] = L.layerGroup().addTo(layerGroup);
        }
        c3nav._levelControl.finalize();
        c3nav._levelControl.setLevel(c3nav.levels[0][0]);

        c3nav.map.on('click', c3nav._click_anywhere);

        c3nav.schedule_refresh_tile_access();

    },
    _click_anywhere_popup: null,
    _click_anywhere: function(e) {
        if (e.originalEvent.target.id !== 'map') return;
        var popup = L.popup().setLatLng(e.latlng).setContent('<div class="loader"></div>'),
            level = c3nav._levelControl.currentLevel,
            name = 'c:'+String(c3nav.level_labels_by_id[level])+':'+Math.round(e.latlng.lng*100)/100+':'+Math.round(e.latlng.lat*100)/100;
        c3nav._click_anywhere_popup = popup;
        popup.on('remove', function() { c3nav._click_anywhere_popup = null }).openOn(c3nav.map);
        $.getJSON('/api/locations/'+name+'/', function(data) {
            if (c3nav._click_anywhere_popup !== popup || !popup.isOpen()) return;
            popup.remove();
            popup = L.popup(c3nav._add_map_padding({className: 'location-popup'}, 'autoPanPaddingTopLeft', 'autoPanPaddingBottomRight'));
            popup.setLatLng(e.latlng).setContent(c3nav._build_location_html(data, true)+$('#popup-buttons').html());
            c3nav._click_anywhere_popup = popup;
            popup.on('remove', function() { c3nav._click_anywhere_popup = null }).openOn(c3nav.map);
        });
    },
    _map_moved: function () {
        c3nav.update_map_state();
    },
    _map_zoomed: function () {
        c3nav.update_map_state();
    },
    _add_icon: function (name) {
        c3nav[name+'Icon'] = new L.Icon({
            iconUrl: '/static/img/marker-icon-'+name+'.png',
            iconRetinaUrl: '/static/img/marker-icon-'+name+'-2x.png',
            shadowUrl: '/static/leaflet/images/marker-shadow.png',
            iconSize: [25, 41],
            iconAnchor: [12, 41],
            popupAnchor: [1, -34],
            tooltipAnchor: [16, -28],
            shadowSize: [41, 41]
        });
    },
    update_map_locations: function () {
        // update locations markers on the map
        var origin = $('#origin-input').data('location'),
            destination = $('#destination-input').data('location'),
            single = !$('main').is('[data-view^=route]'),
            bounds = {};
        for (var level_id in c3nav._locationLayers) {
            c3nav._locationLayers[level_id].clearLayers()
        }
        if (origin) c3nav._merge_bounds(bounds, c3nav._add_location_to_map(origin, single ? new L.Icon.Default() : c3nav.originIcon));
        if (destination) c3nav._merge_bounds(bounds, c3nav._add_location_to_map(destination, single ? new L.Icon.Default() : c3nav.destinationIcon));
        c3nav._locationLayerBounds = bounds;
    },
    fly_to_bounds: function(replace_state, nofly) {
        // fly to the bounds of the current overlays
        var level = c3nav._levelControl.currentLevel,
            bounds = null;

        if (c3nav._firstRouteLevel) {
            level = c3nav._firstRouteLevel;
            bounds = c3nav._routeLayerBounds[level];
        } else if (c3nav._locationLayerBounds[level]) {
            bounds = c3nav._locationLayerBounds[level];
        } else {
            for (var level_id in c3nav._locationLayers) {
                if (c3nav._locationLayerBounds[level_id]) {
                    bounds = c3nav._locationLayerBounds[level_id];
                    level = level_id
                }
            }
        }
        c3nav._levelControl.setLevel(level);
        if (bounds) {
            var target = c3nav.map._getBoundsCenterZoom(bounds, c3nav._add_map_padding({}));
            var center = c3nav.map._limitCenter(target.center, target.zoom, c3nav.map.options.maxBounds);
            if (nofly) {
                c3nav.map.flyTo(center, target.zoom, { animate: false });
            } else {
                c3nav.map.flyTo(center, target.zoom, { duration: 1 });
            }

            if (replace_state) {
                c3nav.update_map_state(true, level, center, target.zoom);
            }
        }
    },
    _add_map_padding: function(options, topleft, bottomright) {
        // add padding information for the current ui layout to fitBoudns options
        var $search = $('#search'),
            $main = $('main'),
            padBesideSidebar = ($main.width() > 1000 && ($main.height() < 250 || c3nav.state.details)),
            left = padBesideSidebar ? ($search.width() || 0)+10 : 0,
            top = padBesideSidebar ? 10 : ($search.height() || 0)+10;
        options[topleft || 'paddingTopLeft'] = L.point(left+13, top+41);
        options[bottomright || 'paddingBottomRight'] = L.point(50, 20);
        return options;
    },
    _get_padded_max_bounds: function(zoom) {
        if (zoom === undefined) zoom = c3nav.map.getZoom();
        var bounds = c3nav.bounds,
            factor = Math.pow(2, zoom);
        return [
            [bounds[0][0]-600/factor, bounds[0][1]-200/factor],
            [bounds[1][0]+600/factor, bounds[1][1]+200/factor]
        ];
    },
    _add_location_to_map: function(location, icon) {
        // add a location to the map as a marker
        if (location.locations) {
            var bounds = {};
            for (var i=0; i<location.locations.length; i++) {
                c3nav._merge_bounds(bounds, c3nav._add_location_to_map(c3nav.locations_by_id[location.locations[i]], icon));
            }
            return bounds;
        }
        var latlng = L.GeoJSON.coordsToLatLng(location.point.slice(1));
        L.marker(latlng, {
            icon: icon
        }).bindPopup(location.elem+$('#popup-buttons').html(), c3nav._add_map_padding({
            className: 'location-popup'
        }, 'autoPanPaddingTopLeft', 'autoPanPaddingBottomRight')).addTo(c3nav._locationLayers[location.point[0]]);

        var result = {};
        result[location.point[0]] = L.latLngBounds(
            location.bounds ? L.GeoJSON.coordsToLatLngs(location.bounds) : [latlng, latlng]
        );
        return result
    },
    _merge_bounds: function(bounds, new_bounds) {
        for (var level_id in new_bounds) {
            bounds[level_id] = bounds[level_id] ? bounds[level_id].extend(new_bounds[level_id]) : new_bounds[level_id];
        }
    },

    schedule_refresh_tile_access: function () {
        window.setTimeout(c3nav.refresh_tile_access, 16000);
    },
    refresh_tile_access: function () {
        $.get('/api/users/current/', c3nav._set_user_data);
        c3nav.schedule_refresh_tile_access();
    },
    _set_user_data: function (data) {
        var $user = $('header #user');
        $user.find('span').text(data.title);
        $user.find('small').text(data.subtitle || '');
    }
};
$(document).ready(c3nav.init);


LevelControl = L.Control.extend({
    options: {
        position: 'bottomright',
        addClasses: ''
    },

    onAdd: function () {
        this._container = L.DomUtil.create('div', 'leaflet-control-levels leaflet-bar ' + this.options.addClasses);
        this._tileLayers = {};
        this._overlayLayers = {};
        this._levelButtons = {};
        this.currentLevel = null;
        return this._container;
    },

    addLevel: function (id, title) {
        this._tileLayers[id] = L.tileLayer((c3nav.tile_server || '/map/') + String(id) + '/{z}/{x}/{y}.png', {
            minZoom: -2,
            maxZoom: 5,
            bounds: L.GeoJSON.coordsToLatLngs(c3nav.bounds)
        });
        var overlay = L.layerGroup();
        this._overlayLayers[id] = overlay;

        var link = L.DomUtil.create('a', '', this._container);
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
        if (this._tileLayers[id] === undefined) return false;

        if (this.currentLevel) {
            this._tileLayers[this.currentLevel].remove();
            this._overlayLayers[this.currentLevel].remove();
            L.DomUtil.removeClass(this._levelButtons[this.currentLevel], 'current');
        }
        this._tileLayers[id].addTo(c3nav.map);
        this._overlayLayers[id].addTo(c3nav.map);
        L.DomUtil.addClass(this._levelButtons[id], 'current');
        this.currentLevel = id;
        return true;
    },

    _levelClick: function (e) {
        e.preventDefault();
        e.stopPropagation();
        this.setLevel(e.target.level);
        c3nav.update_map_state();
    },

    finalize: function () {
        var buttons = $(this._container).find('a');
        buttons.addClass('current');
        buttons.width(buttons.width());
        buttons.removeClass('current');
    }
});
