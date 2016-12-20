c3nav = {
    init: function() {
        if (!$('.main-view').length) return;

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
        $('#route-from-here').click(c3nav._click_route_from_here);
        $('#route-to-here').click(c3nav._click_route_to_here);

        window.onpopstate = c3nav._onpopstate;
    },

    _locationselect_reset: function(e) {
        e.preventDefault();
        var location_group = $(this).closest('.location-group');
        location_group.find('.id-field').val('');
        location_group.removeClass('selected').find('.tt-input').focus().removeData('enter_item');
        location_group,find('.tt-suggestion').remove();
        c3nav._locations_changed();
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
        $('.main-view').removeClass('mode-location').addClass('mode-route');
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
        if ($('.main-view').is('.mode-location')) {
            url = '/l/'+$(':input[name=location]').val()+'/';
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
