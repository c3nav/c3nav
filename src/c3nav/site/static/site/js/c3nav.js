c3nav = {
    init: function() {
        if (!$('#c3nav-main').length) return;

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

        c3nav.update_history_state(true);
        c3nav.init_typeahead($('.locationselect input:text'));

        $('.locationselect:not(.selected) .locationselect-input .tt-input').first().focus();
        $('.locationselect .icons .reset').click(c3nav._locationselect_reset)
    },

    _locationselect_reset: function(e) {
        e.preventDefault();
        var locationselect = $(this).closest('.locationselect');
        locationselect.find('.id-field').val('');
        locationselect.removeClass('selected').find('.tt-input').focus().keyup().removeData('enter_item');
        c3nav.update_history_state();
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
            var target = $(e.target);
            enter_item = target.data('enter_item');
            if (enter_item !== undefined) {
                target.trigger('typeahead:select', [enter_item]);
            }
        }
    },
    _typeahead_select: function(e, item) {
        var locationselect = $(e.target).closest('.locationselect');
        locationselect.addClass('selected');
        var selected = locationselect.find('.locationselect-selected');
        selected.find('.title').text(item.title);
        selected.find('.subtitle').text(item.subtitle);
        selected.find('.id-field').val(item.id);
        e.target.blur();
        c3nav.update_history_state();

        $('.locationselect:not(.selected) .locationselect-input .tt-input').first().focus();
    },
    _typeahead_blur: function(e) {
        $(e.target).val('');
    },
    _typeahead_cursorchange: function(e, item) {
        $(e.target).data('enter_item', item);
    },

    update_history_state: function(e, replace) {
        var origin = $(':input[name=origin]').val();
        var destination = $(':input[name=destination]').val();
        url = '/';
        if (origin !== '') {
            url += origin + '/'
            if (destination !== '') {
                url += destination + '/'
            }
        } else if (destination !== '') {
            url += '_/' + destination + '/'
        }
        if (replace) {
            history.replaceState({}, '', url);
        } else {
            history.pushState({}, '', url);
        }

    }
};
$(document).ready(c3nav.init);
