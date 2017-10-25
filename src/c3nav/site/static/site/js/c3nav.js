(function () {
    if (L.Browser.chrome && !('ontouchstart' in window)) {
        L.Browser.pointer = false;
        L.Browser.touch = false;
    }
}());

c3nav = {
    init: function () {
        // Init Map
        var $map = $('#map');
        c3nav.bounds = JSON.parse($map.attr('data-bounds'));
        c3nav.levels = JSON.parse($map.attr('data-levels'));

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

        L.control.scale({imperial: false}).addTo(c3nav.map);

        c3nav._levelControl = new LevelControl().addTo(c3nav.map);
        for (var i = c3nav.levels.length - 1; i >= 0; i--) {
            var level = c3nav.levels[i];
            c3nav._levelControl.addLevel(level[0], level[1]);
        }
        c3nav._levelControl.finalize();
        c3nav._levelControl.setLevel(c3nav.levels[0][0]);


        window.setTimeout(c3nav.refresh_tile_access, 16000);
    },
    refresh_tile_access: function () {
        $.ajax('/map/tile_access');
        window.setTimeout(c3nav.refresh_tile_access, 16000);
    }
};

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

$(document).ready(c3nav.init);
