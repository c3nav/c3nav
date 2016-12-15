c3nav = {
    init: function() {
        c3nav._typeahead_locations = new Bloodhound({
            datumTokenizer: function(data) {
                var result = [data.name]
                result = result.concat(data.title.split(' '));
                return result
            },
            queryTokenizer: Bloodhound.tokenizers.whitespace,
            identify: function(data) {
                return data.name;
            },
            prefetch: '/api/locations/'
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

        $('.locationselect:not(.selected) .locationselect-input .tt-input').first().focus();
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
        selected.find('.name-field').val(item.name);
        e.target.blur();

        $('.locationselect:not(.selected) .locationselect-input .tt-input').first().focus();
    },
    _typeahead_blur: function(e) {
        $(e.target).val('');
    },
    _typeahead_cursorchange: function(e, item) {
        $(e.target).data('enter_item', item);
    }
};
$(document).ready(c3nav.init);


