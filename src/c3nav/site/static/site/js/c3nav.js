c3nav = {
    init: function() {
        c3nav.main_view = $('.main-view');
        if (!c3nav.main_view.length) return;

        c3nav.svg_width = parseInt(c3nav.main_view.attr('data-svg-width'));
        c3nav.svg_height = parseInt(c3nav.main_view.attr('data-svg-height'));
        c3nav.visible_areas = c3nav.main_view.attr('data-visible-areas').split(';');

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
        $('.locationselect .icons .map').click(c3nav._locationselect_activate_map);
        $('.locationselect .close-map').click(c3nav._locationselect_close_map);
        $('.locationselect .level-selector a').click(c3nav._locationselect_click_level);
        $('.locationselect .map-container').on('click', 'img', c3nav._locationselect_click_image);
        $('#route-from-here').click(c3nav._click_route_from_here);
        $('#route-to-here').click(c3nav._click_route_to_here);

        window.onpopstate = c3nav._onpopstate;
    },

    _locationselect_reset: function(e) {
        e.preventDefault();
        var location_group = $(this).closest('.location-group');
        location_group.find('.id-field').val('');
        location_group.removeClass('selected').find('.tt-input').focus().removeData('enter_item');
        location_group.find('.tt-suggestion').remove();
        c3nav._locations_changed();
    },
    _locationselect_activate_map: function(e) {
        e.preventDefault();
        var location_group = $(this).closest('.location-group');
        location_group.addClass('map');
        var map_container = location_group.find('.map-container');
        console.log(c3nav.svg_height-(map_container.height()/2));
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
        location_group.removeClass('map').addClass('selected');
        var selected = location_group.find('.locationselect-selected');
        selected.find('.title').text('');
        selected.find('.subtitle').text('');
        selected.find('.id-field').val(coords);
        selected.addClass('loading');
        $.getJSON('/api/locations/'+coords, function(data) {
            selected.find('.title').text(data.title);
            selected.find('.subtitle').text(data.subtitle);
            selected.removeClass('loading');
        });
        c3nav._locations_changed();
        c3nav.locationselect_focus();
    },
    locationselect_focus: function() {
        $('.location-group:visible:not(.selected) .locationselect-input .tt-input').first().focus();
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
        $(e.target).data('enter_item', item);
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
$(document).ready(c3nav.init);
