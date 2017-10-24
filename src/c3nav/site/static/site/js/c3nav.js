c3nav = {
    init: function() {
        // Init Map
        c3nav.bounds = JSON.parse($('#map').attr('data-bounds'));
        c3nav.map = L.map('map', {
            renderer: L.svg({ padding: 2 }),
            zoom: 2,
            maxZoom: 10,
            minZoom: 0,
            crs: L.CRS.Simple,
            maxBounds: c3nav.bounds,
            closePopupOnClick: false,
        });
        c3nav.map.fitBounds(c3nav.bounds, {padding: [30, 50]});
        L.control.scale({imperial: false}).addTo(c3nav.map);
        L.tileLayer('/map/7/{z}/{x}/{y}.png', {
            bounds: c3nav.bounds
        }).addTo(c3nav.map);
        window.setTimeout(c3nav.refresh_tile_access, 16000);
    },
    refresh_tile_access: function() {
        $.ajax('/map/tile_access');
        window.setTimeout(c3nav.refresh_tile_access, 16000);
    }
};

$(document).ready(c3nav.init);
