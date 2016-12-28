c3nav = {
    init: function() {
        c3nav.main_view = $('.main-view');
        if (!c3nav.main_view.length) return;

        c3nav.svg_width = parseInt(c3nav.main_view.attr('data-svg-width'));
        c3nav.svg_height = parseInt(c3nav.main_view.attr('data-svg-height'));
        c3nav.visible_areas = c3nav.main_view.attr('data-visible-areas').split(';');
        c3nav.qr_modal = $('#qr_modal');

        c3nav.mobileclient = (typeof mobileclient !== "undefined");
        if (c3nav.mobileclient) {
            $('body').removeClass('nomobileclient');
        }

        c3nav._typeahead_locations = new Bloodhound({
            datumTokenizer: function(data) {
                var result = [data.id]
                result = result.concat(data.title.split(' '));
                return result
            },
            queryTokenizer: Bloodhound.tokenizers.whitespace,
            identify: function(data) {
                return data.id;
            },
            prefetch: {
                url: '/api/locations/',
                cache: false
            }
        });
        c3nav._typeahead_options = {
            source: c3nav._typeahead_locations,
            limit: 7,
            display: function(item) {
                return item.title;
            },
            templates: {
                suggestion: function(data) {
                    return '<div class="location"></span><span>'+data.title+'</span><small>'+data.subtitle+'</small></div>';
                }
            }
        };

        c3nav.init_typeahead($('.locationselect input:text'));
        c3nav.locationselect_focus();

        $('.locationselect .icons .reset').click(c3nav._locationselect_reset);
        $('.locationselect .icons .errorreset').click(c3nav._locationselect_errorreset);
        $('.locationselect .icons .map').click(c3nav._locationselect_activate_map);
        $('.locationselect .icons .link').click(c3nav._locationselect_click_link);
        $('.locationselect .icons .locate').click(c3nav._locationselect_click_locate);
        $('.locationselect .close-map').click(c3nav._locationselect_close_map);
        $('.locationselect .level-selector a').click(c3nav._locationselect_click_level);
        $('.locationselect .map-container').on('click', 'img', c3nav._locationselect_click_image);
        $('.location-group .swap').click(c3nav.swap_locations);
        $('#route-from-here').click(c3nav._click_route_from_here);
        $('#route-to-here').click(c3nav._click_route_to_here);

        c3nav.qr_modal.find('.qr-close').click(function() {
            c3nav.qr_modal.hide();
        });
        c3nav.qr_modal.find('.share').click(function() {
            mobileclient.shareUrl(c3nav.qr_modal.find('strong').text());
        });
        c3nav.qr_modal.find('.shortcut').click(function() {
            mobileclient.createShortcut(c3nav.qr_modal.find('strong').text(), c3nav.qr_modal.data('title'));
        });

        $('.showsettings').show();
        $('.savesettings, .settings').hide();
        $('.showsettings a').click(function(e) {
            e.preventDefault();
            $('.showsettings').hide();
            $('.savesettings, .settings').show();
        });

        window.onpopstate = c3nav._onpopstate;
    },

    swap_locations: function(e) {
        e.preventDefault();
        var origin_select = $('.origin-select');
        var destination_select = $('.destination-select');
        var has_orig = origin_select.is('.selected');
        var has_dest = destination_select.is('.selected');

        var orig_id = '',
            orig_html = '',
            dest_id = '',
            dest_html = '';

        if (has_orig) {
            orig_id = origin_select.find('.id-field').val();
            orig_html = origin_select.find('.locationselect-selected .location').html();
        }
        if (has_dest) {
            dest_id = destination_select.find('.id-field').val();
            dest_html = destination_select.find('.locationselect-selected .location').html();
            destination_select.toggleClass('selected', has_orig);
            destination_select.find('.id_field').val(orig_id);
            destination_select.find('.locationselect-selected .location').html(orig_html);
        }
        if (has_orig) {
            origin_select.toggleClass('selected', has_dest);
            origin_select.find('.id_field').val(dest_id);
            origin_select.find('.locationselect-selected .location').html(dest_html);
        }
    },
    _locationselect_reset: function(e) {
        e.preventDefault();
        var location_group = $(this).closest('.location-group');
        location_group.find('.id-field').val('');
        location_group.removeClass('selected').find('.tt-input').focus().removeData('enter_item');
        location_group.find('.tt-suggestion').remove();
        c3nav._locations_changed();
    },
    _locationselect_errorreset: function(e) {
        e.preventDefault();
        var location_group = $(this).closest('.location-group');
        location_group.removeClass('error').find('.tt-input').focus();
        location_group.find('.tt-suggestion').remove();
    },
    _locationselect_click_link: function(e) {
        e.preventDefault();
        var location_group = $(this).closest('.location-group');
        var location_id = location_group.find('.id-field').val();
        var location_title = location_group.find('.title').text();
        c3nav.qr_modal.find('strong').text(window.location.origin+'/l/'+location_id+'/');
        c3nav.qr_modal.find('img').attr('src', '/qr/'+location_id+'.png');
        c3nav.qr_modal.data('title', location_title);
        c3nav.qr_modal.show();
    },
    _locationselect_activate_map: function(e) {
        e.preventDefault();
        var location_group = $(this).closest('.location-group');
        location_group.addClass('map');
        var map_container = location_group.find('.map-container');
        map_container.scrollTop((c3nav.svg_height-map_container.height())/2).scrollLeft((c3nav.svg_width-map_container.width())/2);
        location_group.find('.level-selector a').first().click();
    },
    _locationselect_close_map: function(e) {
        e.preventDefault();
        var location_group = $(this).closest('.location-group');
        location_group.removeClass('map').find('.tt-input').focus();
    },
    _locationselect_click_level: function(e) {
        e.preventDefault();
        var location_group = $(this).closest('.location-group');
        var map_container = location_group.find('.map-container');
        var level = $(this).attr('data-level');
        $(this).siblings().removeClass('active');
        $(this).addClass('active');
        map_container.find('img').remove();
        for (var i=0;i<c3nav.visible_areas.length;i++) {
            map_container.append($('<img>').attr({
                'src': '/map/'+level+'/'+c3nav.visible_areas[i]+'.png',
                'width': c3nav.svg_width,
                'height': c3nav.svg_height
            }));
        }
        map_container.attr('data-level', level);
    },
    _locationselect_click_image: function(e) {
        var level = $(e.delegateTarget).attr('data-level');
        var coords = 'c:'+level+':'+parseInt(e.offsetX/6*100)+':'+parseInt((c3nav.svg_height-e.offsetY)/6*100);
        var location_group = $(this).closest('.location-group');
        location_group.removeClass('map').addClass('selected').addClass('loading');
        var selected = location_group.find('.locationselect-selected');
        selected.find('.title').text('');
        selected.find('.subtitle').text('');
        selected.find('.id-field').val(coords);
        $.getJSON('/api/locations/'+coords, function(data) {
            selected.find('.title').text(data.title);
            selected.find('.subtitle').text(data.subtitle);
            selected.closest('.location-group').removeClass('loading');
        });
        c3nav._locations_changed();
        c3nav.locationselect_focus();
    },
    locationselect_focus: function() {
        $('.location-group:visible:not(.selected) .locationselect-input .tt-input').first().focus();
    },


    _last_scan: 0,
    _scan_for: [],
    _scan_now: function() {
        if (c3nav._last_scan < (new Date().getTime() / 1000 - 3000)) {
            c3nav._last_scan = new Date().getTime() / 1000;
            mobileclient.scanNow();
        } else {
            nearby_stations_available();
        }
    },
    _locationselect_click_locate: function(e) {
        e.preventDefault();
        var location_group = $(this).closest('.location-group');
        location_group.addClass('loading').addClass('selected');
        c3nav._scan_for.push(location_group.attr('data-name'));
        c3nav._scan_now();
    },
    nearby_stations_available: function() {
        $.ajax({
            type: "POST",
            url: '/api/locations/wifilocate/',
            data: { stations: mobileclient.getNearbyStations() },
            dataType: 'json',
            success: c3nav._wifilocate_callback
        });
    },
    _wifilocate_callback: function(data) {
        var location_group, selected;
        var location = data.location;
        for(var i=0;i<c3nav._scan_for.length;i++) {
            location_group = $('.location-group[data-name='+c3nav._scan_for[i]+']');
            location_group.removeClass('loading');
            selected = location_group.find('.locationselect-selected');
            if (location === null) {
                location_group.addClass('error').removeClass('selected');
            } else {
                selected.find('.id-field').val(location.id);
                selected.find('.title').text(location.title);
                selected.find('.subtitle').text(location.subtitle);
            }
        }
        c3nav._scan_for = [];
    },

    _click_route_from_here: function(e) {
        c3nav._click_route_x_here(e, $('.origin-select'));
    },
    _click_route_to_here: function(e) {
        c3nav._click_route_x_here(e, $('.destination-select'));
    },
    _click_route_x_here: function(e, location_group) {
        e.preventDefault();
        c3nav.main_view.removeClass('mode-location').addClass('mode-route');
        from_group = $('.location-select');
        from_group.removeClass('selected');
        location_group.addClass('selected').find('.id-field').val(from_group.find('.id-field').val());
        location_group.find('.locationselect-selected .location').html(from_group.find('.locationselect-selected .location').html());
        c3nav._locations_changed();
        c3nav.locationselect_focus();
    },

    init_typeahead: function(elem) {
        elem.typeahead(null, c3nav._typeahead_options)
            .on('keydown', c3nav._typeahead_keydown)
            .on('typeahead:select', c3nav._typeahead_select)
            .on('blur', c3nav._typeahead_blur)
            .on('typeahead:cursorchange', c3nav._typeahead_cursorchange)
            .on('typeahead:autocomplete', c3nav._typeahead_cursorchange)
            .on('typeahead:render', c3nav._typeahead_cursorchange);
    },
    _typeahead_keydown: function(e) {
        if (e.which == 13) {
            e.preventDefault();
            var target = $(e.target);
            enter_item = target.data('enter_item');
            if (enter_item !== undefined) {
                target.trigger('typeahead:select', [enter_item]);
            }
        }
    },
    _typeahead_select: function(e, item) {
        var location_group = $(e.target).closest('.location-group');
        location_group.addClass('selected');
        var selected = location_group.find('.locationselect-selected');
        selected.find('.title').text(item.title);
        selected.find('.subtitle').text(item.subtitle);
        selected.find('.id-field').val(item.id);
        e.target.blur();
        c3nav._locations_changed();
        c3nav.locationselect_focus();
    },
    _typeahead_blur: function(e) {
        $(e.target).val('');
    },
    _typeahead_cursorchange: function(e, item) {
        if (item === undefined) {
            $(e.target).removeData('enter_item');
        } else {
            $(e.target).data('enter_item', item);
        }
    },

    _locations_changed: function(e) {
        var url;
        if (c3nav.main_view.is('.mode-location')) {
            var location = $(':input[name=location]').val()
            url = (location !== '') ? '/l/'+location+'/' : '/';
        } else {
            var origin = $(':input[name=origin]').val();
            var destination = $(':input[name=destination]').val();
            if (origin !== '') {
                url = (destination !== '') ? '/r/'+origin+'/'+destination+'/' : '/o/'+origin+'/';
            } else {
                url = (destination !== '') ? '/d/'+destination+'/' : '/';
            }
            $('.main-view').toggleClass('can-route', (origin !== '' && destination !== ''));
        }
        history.pushState({}, '', url);
    },
    _onpopstate: function() {
        document.location.href = document.location;
    }

};
function nearby_stations_available() {
    c3nav.nearby_stations_available();
}
// mobileclient = { getNearbyStations: function() { return '[{"bssid": "00:00:00:00:00:01", "level": 10}]'; }, scanNow: function() { nearby_stations_available(); } };

$(document).ready(c3nav.init);
