import {Api} from "../api/api";

export class Map {
    root;
    anywhereButtons;
    locationButtons;
    map;

    bounds;
    levels;
    initial_level;

    level_labels_by_id = {};
    visible_map_locations = [];

    locationLayers = {};
    locationLayerBounds = {};
    detailLayers = {};
    routeLayers = {};
    routeLayerBounds = {};
    userLocationLayers = {};
    firstRouteLevel = null;

    location_point_overrides = {};

    levelControl;
    labelControl;
    labelLayer;

    tile_server;

    anywherePopup = null;

    constructor(root: HTMLElement, private api: Api) {
        this.root = root;
        this.tile_server = root.dataset.tileServer ?? '/map/';

        this.anywhereButtons = document.querySelector('#anywhere-popup-buttons').cloneNode(true);
        this.locationButtons = document.querySelector('#location-popup-buttons').cloneNode(true);
        this.bounds = JSON.parse(this.root.dataset.bounds);
        this.levels = JSON.parse(this.root.dataset.levels);
        if (this.root.dataset.hasOwnProperty('initialLevel')) {
            this.initial_level = parseInt(this.root.dataset.initialLevel);
        } else if (this.levels.length > 0) {
            this.initial_level = this.levels[0][0];
        } else {
            this.initial_level = 0;
        }

        for (const level of this.levels) {
            this.level_labels_by_id[level[0]] = level[1];
        }

    }

    init = ({width, height}) => {
        const minZoom = Math.log2(Math.max(0.25, Math.min(
            (width) / (this.bounds[1][0] - this.bounds[0][0]),
            (height) / (this.bounds[1][1] - this.bounds[0][1])
        )));

        const factor = Math.pow(2, minZoom);
        const maxBounds = [
            [this.bounds[0][0] - 600 / factor, this.bounds[0][1] - 200 / factor],
            [this.bounds[1][0] + 600 / factor, this.bounds[1][1] + 200 / factor]
        ];

        this.map = L.map(this.root, {
            renderer: L.svg({padding: 2}),
            zoom: 0,
            maxZoom: 5,
            minZoom: minZoom,
            crs: L.CRS.Simple,
            maxBounds: L.GeoJSON.coordsToLatLngs(maxBounds),
            zoomSnap: 0,
            zoomControl: false,
            attributionControl: !window.mobileclient,
        });
        if (!window.mobileclient) this.map.attributionControl.setPrefix(document.querySelector('#attributions').innerHTML);

        if (!('ontouchstart' in window || navigator.maxTouchPoints)) {
            this.root.classList.remove('leaflet-touch');
        }


        let initial_bounds;
        if (this.root.dataset.hasOwnProperty('initialBounds')) {
            const bounds = JSON.parse(this.root.dataset.initialBounds);
            initial_bounds = [bounds.slice(0, 2), bounds.slice(2)];
        } else {
            initial_bounds = this.bounds;
        }

        this.map.fitBounds(L.GeoJSON.coordsToLatLngs(initial_bounds), c3nav._add_map_padding({}));

        this.map.on('moveend', this.map_moved);
        this.map.on('zoomend', this.map_zoomed);

        // setup scale control
        L.control.scale({imperial: false}).addTo(this.map);

        // setup level control
        this.levelControl = new LevelControl().addTo(this.map);
        for (const level of this.levels.toReversed()) {
            const layerGroup = this.levelControl.addLevel(level[0], level[1]);
            this.detailLayers[level[0]] = L.layerGroup().addTo(layerGroup);
            this.locationLayers[level[0]] = L.layerGroup().addTo(layerGroup);
            this.routeLayers[level[0]] = L.layerGroup().addTo(layerGroup);
            this.userLocationLayers[level[0]] = L.layerGroup().addTo(layerGroup);
        }
        this.levelControl.finalize();
        this.levelControl.setLevel(this.initial_level);

        this.labelLayer = L.LayerGroup.collision({margin: 5}).addTo(this.map);
        this.labelControl = new LabelControl().addTo(this.map);


        if (c3nav.settings.get('hideLabels', false)) {
            this.labelControl.hideLabels();
        }


        L.control.zoom({
            position: 'bottomright'
        }).addTo(this.map);

        // setup grid control
        if (this.root.dataset.hasOwnProperty('grid')) {
            c3nav._gridLayer = new L.SquareGridLayer(JSON.parse(this.root.dataset.grid));
            c3nav._gridControl = new SquareGridControl().addTo(this.map);
        }

        // setup user location control
        c3nav._userLocationControl = new UserLocationControl().addTo(this.map);


        this.map.on('click', this.click_anywhere);

        on(this.root, 'click', '.location-popup .button-clear', this.popup_button_click);
    }

    map_moved = () => {
        c3nav.update_map_state();
        c3nav.update_location_labels();
    }

    map_zoomed = () => {
        c3nav.update_map_state();
        c3nav.update_location_labels();
    }

    click_anywhere = e => {
        if (e.originalEvent.target !== this.root) return;

        const popup = L.popup(c3nav._add_map_padding({
                className: 'location-popup',
                maxWidth: 500
            }, 'autoPanPaddingTopLeft', 'autoPanPaddingBottomRight')),
            name = c3nav._latlng_to_name(e.latlng);
        const buttons = this.anywhereButtons;
        buttons.querySelector('.report').href = `/report/l/${name}/`;
        buttons.querySelector('.set-position').href = `/positions/set/${name}/`;
        popup.setLatLng(e.latlng).setContent(buttons.innerHTML); // TODO: try using a document fragment
        this.anywherePopup = popup;
        popup.on('remove', () => {
            this.anywherePopup = null
        }).openOn(this.map);
    }

    click_anywhere_load = async nearby => {
        if (!this.anywherePopup) return;
        const latlng = this.anywherePopup.getLatLng();
        this.anywherePopup.remove();
        const popup = L.popup()
            .setLatLng(latlng)
            .setContent(<div className="loader"/>);
        const name = c3nav._latlng_to_name(latlng);
        this.anywherePopup = popup;
        popup.on('remove', () => {
            this.anywherePopup = null
        }).openOn(this.map);

        try {
            const data = await this.api.map.mapLocationById(name);
            if (this.anywherePopup !== popup || !popup.isOpen()) return;
            popup.remove();
            if (nearby) {
                c3nav.sidebar.destination.set(data);
                c3nav.update_state(false, false, false, false, true);
            } else {
                const newpopup = L.popup(c3nav._add_map_padding({
                    className: 'location-popup',
                    maxWidth: 500
                }, 'autoPanPaddingTopLeft', 'autoPanPaddingBottomRight'));
                const buttons = this.locationButtons.cloneNode(true);
                buttons.querySelector('.report-issue').remove();
                buttons.querySelector('.report').href = `/report/l/${data.id}/`;
                newpopup.setLatLng(latlng)
                    .setContent(c3nav._build_location_html(data).outerHTML + buttons.innerHTML);
                this.anywherePopup = newpopup;
                newpopup.on('remove', () => {
                    this.anywherePopup = null
                }).openOn(this.map);
            }
        } catch (e) {
            console.log(e);
            popup.remove();
        }
    }

    popup_button_click = (e, el) => {
        e.stopPropagation();
        const $location = [...el.parentElement.parentElement.children].find(x => x.matches('.location'));
        if ($location) {
            let location = c3nav.locations_by_id[parseInt($location.dataset.id)];
            if (!location) {
                location = JSON.parse($location.dataset.location);
            }
            if (el.matches('.as-location')) {
                c3nav.sidebar.destination.set(location);
                c3nav.update_state(false);
            } else if (el.matches('.share')) {
                c3nav._buttons_share_click(location);
            } else if (el.matches('a')) {
                c3nav.link_handler_modal.call(this, e, el);
            } else {
                const locationinput = el.matches('.as-origin') ? c3nav.sidebar.origin : c3nav.sidebar.destination,
                    other_locationinput = el.matches('.as-origin') ? c3nav.sidebar.destination : c3nav.sidebar.origin,
                    other_location = other_locationinput.location;
                locationinput.set(location);
                if (other_location && (other_location.id === location.id || (other_location.locations && other_location.locations.includes(location.id)))) {
                    other_locationinput.set(null);
                }
                c3nav.update_state(true);
            }
            if (this.anywherePopup) this.anywherePopup.remove();
        } else {
            if (el.matches('.select-point')) {
                this.click_anywhere_load(false);
            } else if (el.matches('.show-nearby')) {
                this.click_anywhere_load(true);
            } else if (el.matches('a')) {
                c3nav.link_handler_modal.call(this, e, el);
            }
        }
    }

    remove_popup = () => {
        if (this.anywherePopup) {
            this.anywherePopup.remove();
        }
    }

    add_location = (location, icon, no_geometry = false) => {
        if (!location) {
            // if location is not in the searchable list...
            return;
        }
        if (location.dynamic) {
            if (!('available' in location)) {
                c3nav.json_get(`/api/locations/dynamic/${location.id}/`)
                    .then(c3nav._dynamic_location_loaded);
                return;
            } else if (!location.available) {
                return;
            }
        }
        // add a location to the map as a marker
        if (location.locations) {
            const bounds = {};
            for (const loc of location.locations) {
                c3nav._merge_bounds(bounds, this.add_location(c3nav.locations_by_id[loc], icon, true));
            }
            return bounds;
        }

        if (!no_geometry && this.visible_map_locations.indexOf(location.id) === -1) {
            this.visible_map_locations.push(location.id);
            c3nav.json_get(`/api/locations/${location.id}/geometry/`)
                .then(c3nav._location_geometry_loaded)
        }

        if (!location.point) return;

        const point = this.location_point_overrides[location.id] || location.point.slice(1);
        const latlng = L.GeoJSON.coordsToLatLng(point);
        const buttons = this.locationButtons.cloneNode(true);
        if (typeof location.id == 'number') {
            buttons.querySelector('.report-missing').remove();
        } else {
            buttons.querySelector('.report-issue').remove();
        }
        buttons.querySelector('.report').href = `/report/l/${location.id}/`;

        L.marker(latlng, {
            icon: icon
        }).bindPopup(c3nav._build_location_html(location).outerHTML + buttons.innerHTML, c3nav._add_map_padding({
            className: 'location-popup',
            maxWidth: 500
        }, 'autoPanPaddingTopLeft', 'autoPanPaddingBottomRight')).addTo(c3nav.map.locationLayers[location.point[0]]);

        const result = {};
        result[location.point[0]] = L.latLngBounds(
            location.bounds ? L.GeoJSON.coordsToLatLngs(location.bounds) : [latlng, latlng]
        );
        return result;
    }

    get center() {
        return this.map.getCenter();
    }

    get zoom() {
        return this.map.getZoom();
    }

    get view_bounds() {
        return this.map.getBounds();
    }

    limitCenter = (center, zoom) => {
        return this.map._limitCenter(center, zoom, this.map.options.maxBounds);
    }

    getBoundsCenterZoom = (bounds, options) => this.map._getBoundsCenterZoom(bounds, options);

    setView = (center, zoom, options) => this.map.setView(center, zoom, options)

    flyTo = (center, zoom, options) => this.map.flyTo(center, zoom, options)

    fly_to_bounds = (replace_state, nofly) => {
        let level = this.levelControl.currentLevel;
        let bounds = null;
        if (this.firstRouteLevel) {
            level = this.firstRouteLevel;
            bounds = this.routeLayerBounds[level];
        } else if (this.locationLayerBounds[level]) {
            bounds = this.locationLayerBounds[level];
        } else {
            for (const level_id in this.locationLayers) {
                if (this.locationLayerBounds[level_id]) {
                    bounds = this.locationLayerBounds[level_id];
                    level = level_id;
                }
            }
        }
        this.levelControl.setLevel(level);
        if (bounds) {
            const target = this.getBoundsCenterZoom(bounds, c3nav._add_map_padding({}));
            const center = this.limitCenter(target.center, target.zoom);
            this.map.flyTo(center, target.zoom, nofly ? {
                animate: false,
            } : {
                duration: 1,
            });
            if (replace_state) {
                c3nav.update_map_state(true, level, center, target.zoom);
            }
        }
    }

    add_line_to_route = (level: number, coords: [[number, number], [number, number]], gray: boolean, link_to_level: boolean) => {
        if (coords.length < 2) {
            console.warn('invalid coords');
            return;
        }
        const latlngs = L.GeoJSON.coordsToLatLngs(c3nav._smooth_line(coords));
        const routeLayer = this.routeLayers[level];
        const line = L.polyline(latlngs, {
            color: gray ? '#888888' : c3nav._primary_color,
            dashArray: (gray || link_to_level) ? '7' : null,
            interactive: false,
            smoothFactor: 0.5
        }).addTo(routeLayer);
        const bounds = {};
        bounds[level] = line.getBounds();

        c3nav._merge_bounds(this.routeLayerBounds, bounds);

        if (link_to_level) {
            L.polyline(latlngs, {
                opacity: 0,
                weight: 15,
                interactive: true
            })
                .addTo(routeLayer)
                .on('click', () => {
                    this.levelControl.setLevel(link_to_level);
                });
        }

    }

    add_location_point_override = (location: C3NavLocation, item) => {
        if (location.type === 'level' || location.type === 'space' || location.type === 'area') {
            this.location_point_overrides[location.id] = item.coordinates.slice(0, -1);
            return true;
        }
        return false;
    }

    update_locations = (single) => {
        for (const level_id in this.locationLayers) {
            this.locationLayers[level_id].clearLayers();
        }

        const bounds = {};
        const origin = c3nav.sidebar.origin.location;
        const destination = c3nav.sidebar.destination.location;

        if (origin) {
            c3nav._merge_bounds(bounds, this.add_location(origin, single ? new L.Icon.Default() : c3nav.originIcon));
        }
        if (destination) {
            c3nav._merge_bounds(bounds, this.add_location(destination, single ? new L.Icon.Default() : c3nav.destinationIcon));
        }
        const done = [];
        if (c3nav.state.nearby && destination && 'areas' in destination) {
            if (destination.space) {
                c3nav._merge_bounds(bounds, this.add_location(c3nav.locations_by_id[destination.space], c3nav.nearbyIcon, true));
            }
            if (destination.near_area) {
                done.push(destination.near_area);
                c3nav._merge_bounds(bounds, this.add_location(c3nav.locations_by_id[destination.near_area], c3nav.nearbyIcon, true));
            }
            for (var area of destination.areas) {
                done.push(area);
                c3nav._merge_bounds(bounds, this.add_location(c3nav.locations_by_id[area], c3nav.nearbyIcon, true));
            }
            for (var location of destination.nearby) {
                if (location in done) continue;
                c3nav._merge_bounds(bounds, this.add_location(c3nav.locations_by_id[location], c3nav.nearbyIcon, true));
            }
        }
        this.locationLayerBounds = bounds;
    }

}