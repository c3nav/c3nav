(function () {
    if (L.Browser.chrome && !('ontouchstart' in window)) {
        L.Browser.pointer = false;
        L.Browser.touch = false;
    }
}());

c3nav = {
    init: function () {
        c3nav.init_locationinputs();
        c3nav.init_map();
    },

    init_locationinputs: function () {
        c3nav.locations = [];
        c3nav.locations_by_slug = {};
        c3nav.current_locationinput = null;
        c3nav._last_match_words_key = null;
        $.getJSON('/api/locations/?searchable', function (data) {
            for (var i = 0; i < data.length; i++) {
                var location = data[i];
                location.elem = $('<div class="location">').append($('<span>').text(location.title))
                    .append($('<small>').text(location.subtitle)).attr('data-slug', location.slug);
                location.title_words = location.title.toLowerCase().split(/\s+/);
                location.match = ' ' + location.title_words.join(' ') + ' ';
                c3nav.locations.push(location);
                c3nav.locations_by_slug[location.slug] = location;
            }
        });

        $('.locationinput input').on('input', c3nav._locationinput_input)
            .on('blur', c3nav._locationinput_blur)
            .on('keydown', c3nav._locationinput_keydown);
        $('.locationinput .clear').on('click', c3nav._locationinput_clear);
        $('#autocomplete').on('mouseover', '.location', c3nav._locationinput_hover_suggestion)
            .on('click', '.location', c3nav._locationinput_click_suggestion);
        $('html').on('focus', '*', c3nav._locationinput_global_focuschange)
    },
    _locationinput_set: function (elem, location) {
        // set a location input
        c3nav._locationinput_reset_autocomplete();
        if (location === null || location === undefined) {
            elem.removeClass('selected').addClass('empty').data('location', null).data('lastlocation', null);
            elem.find('input').val('').data('origval', null);
            elem.find('small').text('');
            return;
        }
        elem.addClass('selected').removeClass('empty').data('location', location).data('lastlocation', location);
        elem.find('input').val(location.title).data('origval', null);
        elem.find('small').text(location.subtitle);
    },
    _locationinput_reset: function (elem) {
        // reset this locationinput to its last location
        c3nav._locationinput_set(elem, elem.data('lastlocation'));
    },
    _locationinput_clear: function () {
        // clear this locationinput
        c3nav._locationinput_set($(this).parent(), null);
        $(this).parent().find('input').focus();
    },
    _locationinput_reset_autocomplete: function () {
        // hide autocomplete
        $autocomplete = $('#autocomplete');
        $autocomplete.find('.focus').removeClass('focus');
        $autocomplete.html('');
        c3nav._last_locationinput_words_key = null;
        c3nav.current_locationinput = null;
    },
    _locationinput_blur: function () {
        // when a locationinput is blurred…
        var location = $(this).parent().data('location');
        if (location !== null && location !== undefined) {
            // if the current content is a location name, set it
            c3nav._locationinput_set($(this).parent(), location);
        } else {
            // otherwise, forget the last location
            $(this).parent().data('lastlocation', null);
        }
    },
    _locationinput_global_focuschange: function () {
        // when focus changed, reset autocomplete if it is outside of locationinputs or autocomplete
        if (c3nav.current_locationinput === null) return;
        if ($('#autocomplete > :focus, #' + c3nav.current_locationinput + ' > :focus').length === 0) {
            c3nav._locationinput_reset_autocomplete();
        }
    },
    _locationinput_keydown: function (e) {
        var $autocomplete = $('#autocomplete'), $focused, origval;
        if (e.which === 27) {
            // escape: reset the location input
            origval = $(this).data('origval');
            if (origval !== null) {
                $(this).val(origval);
                $(this).data('origval', null);
                $autocomplete.find('.focus').removeClass('focus')
            } else {
                c3nav._locationinput_reset($(this).parent());
            }
        } else if (e.which === 40 || e.which === 38) {
            // arrows up/down
            var $locations = $autocomplete.find('.location');
            if ($locations.length === 0) return;

            // save current input value in case we have to restore it
            origval = $(this).data('origval');
            if (origval === null || origval === undefined) {
                origval = $(this).val();
                $(this).data('origval', origval)
            }

            // find focused element and remove focus
            $focused = $locations.filter('.focus');
            $locations.removeClass('focus');

            // find next element
            var next;
            if ($focused.length === 0) {
                next = $locations.filter((e.which === 40) ? ':first-child' : ':last-child');
            } else {
                next = (e.which === 40) ? $focused.next() : $focused.prev();
            }

            if (next.length === 0) {
                // if there is no next element, restore original value
                $(this).val($(this).data('origval')).parent().data('location', null);
            } else {
                // otherwise, focus this element, and save location to the input
                next.addClass('focus');
                $(this).val(next.find('span').text()).parent()
                    .data('location', c3nav.locations_by_slug[next.attr('data-slug')]);
            }
        } else if (e.which === 13) {
            // enter: select currently focused suggestion or first suggestion
            $focused = $autocomplete.find('.location.focus');
            if ($focused.length === 0) {
                $focused = $autocomplete.find('.location:first-child');
            }
            if ($focused.length === 0) return;
            c3nav._locationinput_set($(this).parent(), c3nav.locations_by_slug[$focused.attr('data-slug')])
        }
    },
    _locationinput_hover_suggestion: function () {
        $(this).addClass('focus').siblings().removeClass('focus');
    },
    _locationinput_click_suggestion: function () {
        c3nav._locationinput_set($('#' + c3nav.current_locationinput), c3nav.locations_by_slug[$(this).attr('data-slug')])
    },
    _locationinput_matches_compare: function (a, b) {
        if (a[1] !== b[1]) return b[1] - a[1];
        if (a[2] !== b[2]) return b[2] - a[2];
        if (a[3] !== b[3]) return b[3] - a[3];
        return a[4] - b[4];
    },
    _locationinput_input: function () {
        var matches = [],
            val = $(this).data('origval', null).val(),
            val_trimmed = $.trim(val),
            val_words = val_trimmed.toLowerCase().split(/\s+/),
            val_words_key = val_words.join(' '),
            $autocomplete = $('#autocomplete');
        $(this).parent().removeClass('selected').data('location', null);
        $autocomplete.find('.focus').removeClass('focus');
        c3nav.current_locationinput = $(this).parent().attr('id');

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

    init_map: function () {
        var $map = $('#map');
        c3nav.bounds = JSON.parse($map.attr('data-bounds'));
        c3nav.levels = JSON.parse($map.attr('data-levels'));

        // create leaflet map
        c3nav.map = L.map('map', {
            renderer: L.svg({padding: 2}),
            zoom: 2,
            maxZoom: 10,
            minZoom: 0,
            crs: L.CRS.Simple,
            maxBounds: c3nav.bounds,
            closePopupOnClick: false,
            zoomControl: false
        });
        c3nav.map.fitBounds(c3nav.bounds, {padding: [30, 50]});

        // setup scale control
        L.control.scale({imperial: false}).addTo(c3nav.map);

        // setup level control
        c3nav._levelControl = new LevelControl().addTo(c3nav.map);
        for (var i = c3nav.levels.length - 1; i >= 0; i--) {
            var level = c3nav.levels[i];
            c3nav._levelControl.addLevel(level[0], level[1]);
        }
        c3nav._levelControl.finalize();
        c3nav._levelControl.setLevel(c3nav.levels[0][0]);

        c3nav.schedule_refresh_tile_access();

    },

    schedule_refresh_tile_access: function () {
        window.setTimeout(c3nav.refresh_tile_access, 16000);
    },
    refresh_tile_access: function () {
        $.ajax('/map/tile_access');
        c3nav.schedule_refresh_tile_access();
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
        this._tileLayers[id] = L.tileLayer('/map/' + String(id) + '/{z}/{x}/{y}.png', {
            bounds: c3nav.bounds
        });
        this._overlayLayers[id] = L.layerGroup();

        var link = L.DomUtil.create('a', '', this._container);
        link.innerHTML = title;
        link.level = id;
        link.href = '#';

        L.DomEvent
            .on(link, 'mousedown dblclick', L.DomEvent.stopPropagation)
            .on(link, 'click', this._levelClick, this);

        this._levelButtons[id] = link;
        return link;
    },

    setLevel: function (id) {
        if (this._tileLayers[id] === undefined) {
            return false;
        }
        if (this.currentLevel !== null) {
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
    },

    finalize: function () {
        var buttons = $(this._container).find('a');
        buttons.addClass('current');
        buttons.width(buttons.width());
        buttons.removeClass('current');
    }
});
