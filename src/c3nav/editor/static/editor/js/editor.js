editor = {
    feature_types: {},
    feature_types_order: [],
    _highlight_layer: null,

    init: function () {
        // Init Map
        editor.map = L.map('map', {
            zoom: 2,
            maxZoom: 10,
            minZoom: 1,
            crs: L.CRS.Simple,
            editable: true,
            closePopupOnClick: false
        });
        editor.map.on('click', function (e) {
            editor.map.doubleClickZoom.enable();
        });

        L.control.scale({imperial: false}).addTo(editor.map);

        $('#show_map').click(function() {
            $('body').removeClass('controls');
        });
        $('#show_details').click(function() {
            $('body').addClass('controls');
        });

        editor.init_geometries();
        editor.init_sidebar();
        editor.get_packages();
        editor.get_sources();
        editor.get_levels();
    },

    // packages
    packages: {},
    get_packages: function () {
        // load packages
        $.getJSON('/api/packages/', function (packages) {
            var bounds = [[0, 0], [0, 0]];
            var pkg;
            for (var i = 0; i < packages.length; i++) {
                pkg = packages[i];
                editor.packages[pkg.name] = pkg;
                if (pkg.bounds === null) continue;
                bounds = [[Math.min(bounds[0][0], pkg.bounds[0][0]), Math.min(bounds[0][1], pkg.bounds[0][1])],
                    [Math.max(bounds[1][0], pkg.bounds[1][0]), Math.max(bounds[1][1], pkg.bounds[1][1])]];
            }
            editor.map.setMaxBounds(bounds);
            editor.map.fitBounds(bounds, {padding: [30, 50]});
        });
    },

    // sources
    sources: {},
    get_sources: function () {
        // load sources
        $.getJSON('/api/sources/', function (sources) {
            var layers = {};
            var source;
            for (var i = 0; i < sources.length; i++) {
                source = sources[i];
                editor.sources[source.name] = source;
                source.layer = L.imageOverlay('/api/sources/' + source.name + '/image/', source.bounds);
                layers[source.name] = source.layer;
            }
            L.control.layers([], layers).addTo(editor.map);
        });
    },

    // levels
    levels: {},
    _level: null,
    get_levels: function () {
        // load levels and set the lowest one afterwards
        $.getJSON('/api/levels/?ordering=-altitude', function (levels) {
            L.LevelControl = L.Control.extend({
                options: {
                    position: 'bottomright'
                },
                onAdd: function () {
                    var container = L.DomUtil.create('div', 'leaflet-control leaflet-bar leaflet-levels'), link;
                    var level;
                    for (var i = 0; i < levels.length; i++) {
                        level = levels[i];
                        link = L.DomUtil.create('a', (i == levels.length - 1) ? 'current' : '', container);
                        link.name = level.name;
                        link.innerHTML = level.name;
                        link.href = '';
                    }
                    return container;
                }
            });
            editor.map.addControl(new L.LevelControl());

            $('.leaflet-levels').on('click', 'a', function (e) {
                e.preventDefault();
                editor.set_current_level($(this).attr('name'));
            });

            editor.set_current_level(levels[levels.length - 1].name);
        });
    },
    set_current_level: function(level_name) {
        // sets the current level if the sidebar allows it
        var level_switch = $('#mapeditcontrols ').find('[data-level-switch]');
        if (level_switch.length === 0) return;
        editor._level = level_name;
        $('.leaflet-levels .current').removeClass('current');
        $('.leaflet-levels a[name='+level_name+']').addClass('current');
        editor.get_geometries();

        var level_switch_href = level_switch.attr('data-level-switch');
        if (level_switch_href) {
            editor.sidebar_get(level_switch_href.replace('LEVEL', level_name));
        }
    },

    // geometries
    _geometries_layer: null,
    _highlight_layer: null,
    _editing_layer: null,
    _get_geometries_next_time: false,
    _geometries: {},
    _creating: false,
    _editing: null,
    init_geometries: function () {
        // init geometries and edit listeners
        editor._highlight_layer = L.layerGroup().addTo(editor.map);
        editor._editing_layer = L.layerGroup().addTo(editor.map);

        $('#mapeditcontrols').on('mouseenter', '.itemtable tr[name]', editor._hover_mapitem_row)
                             .on('mouseleave', '.itemtable tr[name]', editor._unhighlight_geometry);

        editor.map.on('editable:drawing:commit', editor._done_creating);
        editor.map.on('editable:editing', editor._update_editing);
        editor.map.on('editable:drawing:cancel', editor._canceled_creating);
    },
    get_geometries: function () {
        // reload geometries of current level
        editor._geometries = {};
        if (editor._geometries_layer !== null) {
            editor.map.removeLayer(editor._geometries_layer);
        }
        $.getJSON('/api/geometries/?level='+String(editor._level), function(geometries) {
            editor._geometries_layer = L.geoJSON(geometries, {
                style: editor._get_geometry_style,
                onEachFeature: editor._register_geojson_feature,
            });

            editor._geometries_layer.addTo(editor.map);
        });
    },
    _geometry_colors: {
        'building': '#333333',
        'area': '#FFFFFF',
        'obstacle': '#999999',
        'door': '#FF00FF',
    },
    _get_geometry_style: function (feature) {
        // style callback for GeoJSON loader
        return editor._get_mapitem_type_style(feature.properties.type);
    },
    _get_mapitem_type_style: function (mapitem_type) {
        // get styles for a specific mapitem
        return {
            fillColor: editor._geometry_colors[mapitem_type],
            weight: 0,
            fillOpacity: 0.6,
            smoothFactor: 0,
        };
    },
    _register_geojson_feature: function (feature, layer) {
        // onEachFeature callback for GeoJSON loader – register all needed events
        editor._geometries[feature.properties.type+'-'+feature.properties.name] = layer;
        layer.on('mouseover', editor._hover_geometry_layer)
             .on('mouseout', editor._unhighlight_geometry)
             .on('click', editor._click_geometry_layer)
             .on('dblclick', editor._dblclick_geometry_layer)
    },

    // hover and highlight geometries
    _hover_mapitem_row: function (e) {
        // hover callback for a itemtable row
        editor._highlight_geometry($(this).closest('.itemtable').attr('data-mapitem-type'), $(this).attr('name'));
    },
    _hover_geometry_layer: function (e) {
        // hover callback for a geometry layer
        editor._highlight_geometry(e.target.feature.properties.type, e.target.feature.properties.name);
    },
    _click_geometry_layer: function (e) {
        // click callback for a geometry layer – scroll the corresponding itemtable row into view if it exists
        var properties = e.target.feature.properties;
        var row = $('.itemtable[data-mapitem-type='+properties.type+'] tr[name='+properties.name+']');
        if (row.length) {
            row[0].scrollIntoView();
        }
    },
    _dblclick_geometry_layer: function (e) {
        // dblclick callback for a geometry layer - edit this feature if the corresponding itemtable row exists
        var properties = e.target.feature.properties;
        var row = $('.itemtable[data-mapitem-type='+properties.type+'] tr[name='+properties.name+']');
        if (row.length) {
            row.find('td:last-child a').click();
            editor.map.doubleClickZoom.disable();
        }
    },
    _highlight_geometry: function(mapitem_type, name) {
        // highlight a geometries layer and itemtable row if they both exist
        var pk = mapitem_type+'-'+name;
        editor._unhighlight_geometry();
        var layer = editor._geometries[pk];
        var row = $('.itemtable[data-mapitem-type='+mapitem_type+'] tr[name='+name+']');
        if (layer !== undefined && row.length) {
            row.addClass('highlight');
            L.geoJSON(layer.feature, {
                style: function() {
                    return {
                        color: '#FFFFDD',
                        weight: 3,
                        opacity: 0.7,
                        fillOpacity: 0,
                        className: 'c3nav-highlight'
                    };
                }
            }).addTo(editor._highlight_layer);
        }
    },
    _unhighlight_geometry: function() {
        // unhighlight whatever is highlighted currently
        editor._highlight_layer.clearLayers();
        $('.itemtable .highlight').removeClass('highlight');
    },

    // edit and create geometries
    _check_start_editing: function() {
        // called on sidebar load. start editing or creating depending on how the sidebar may require it
        var geometry_field = $('#mapeditcontrols').find('input[name=geometry]');
        if (geometry_field.length) {
            var form = geometry_field.closest('form');
            var mapitem_type = form.attr('data-mapitem-type');
            if (form.is('[data-name]')) {
                // edit existing geometry
                var name = form.attr('data-name');
                var pk = mapitem_type+'-'+name;
                editor._geometries_layer.removeLayer(editor._geometries[pk]);

                editor._editing = L.geoJSON({
                    type: 'Feature',
                    geometry: JSON.parse(geometry_field.val()),
                    properties: {
                        type: mapitem_type,
                    }
                }, {
                    style: editor._get_geometry_style
                }).getLayers()[0];
                editor._editing.on('click', editor._click_editing_layer);
                editor._editing.addTo(editor._editing_layer);
                editor._editing.enableEdit();
            } else if (form.is('[data-geomtype]')) {
                // create new geometry
                var geomtype = form.attr('data-geomtype');

                var options = editor._get_mapitem_type_style(mapitem_type);
                if (geomtype == 'polygon') {
                    editor.map.editTools.startPolygon(null, options);
                } else if (geomtype == 'polyline') {
                    editor.map.editTools.startPolyline(null, options);
                }
                editor._creating = true;
                $('#id_level').val(editor._level);
            }
        } else if (editor._get_geometries_next_time) {
            editor.get_geometries();
            editor._get_geometries_next_time = false;
        }
    },
    _cancel_editing: function() {
        // called on sidebar unload. cancel all editing and creating.
        if (editor._editing !== null) {
            editor._editing_layer.clearLayers();
            editor._editing.disableEdit();
            editor._editing = null;
            editor._get_geometries_next_time = true;
        }
        if (editor._creating) {
            editor._creating = false;
            editor.map.editTools.stopDrawing();
        }
    },
    _canceled_creating: function (e) {
        // called after we canceled creating so we can remove the temporary layer.
        if (!editor._creating) {
            e.layer.remove();
        }
    },
    _click_editing_layer: function(e) {
        // click callback for a currently edited layer. create a hole on ctrl+click.
        if ((e.originalEvent.ctrlKey || e.originalEvent.metaKey)) {
            if (e.target.feature.geometry.type == 'Polygon') {
                this.editor.newHole(e.latlng);
            }
        }
    },
    _done_creating: function(e) {
        // called when creating is completed (by clicking on the last point). fills in the form and switches to editing.
        if (editor._creating) {
            editor._creating = false;
            editor._editing = e.layer;
            editor._editing.addTo(editor._editing_layer);
            editor._editin.on('click', editor._click_editing_layer);
            editor._update_editing();
        }
    },
    _update_editing: function () {
        // called if the temporary drawing layer changes. if we are in editing mode (not creating), update the form.
        if (editor._editing !== null) {
            $('#id_geometry').val(JSON.stringify(editor._editing.toGeoJSON().geometry));
        }
    },

    // sidebar
    sidebar_location: null,
    init_sidebar: function() {
        // init the sidebar. sed listeners for form submits and link clicks
        $('#mapeditcontrols').on('click', 'a[href]', editor._sidebar_link_click)
                             .on('click', 'button[type=submit]', editor._sidebar_submit_btn_click)
                             .on('submit', 'form', editor._sidebar_submit);;

        editor.sidebar_get('mapitemtypes/'+String(editor._level)+'/');
    },
    sidebar_get: function(location) {
        // load a new page into the sidebar using a GET request
        editor._sidebar_unload();
        $.get(location, editor._sidebar_loaded);
    },
    _sidebar_unload: function(location) {
        // unload the sidebar. called on sidebar_get and form submit.
        $('#mapeditcontrols').html('').addClass('loading');
        editor._unhighlight_geometry();
        editor._cancel_editing();
    },
    _sidebar_loaded: function(data) {
        // sidebar was loaded. load the content. check if there are any redirects. call _check_start_editing.
        var content = $(data);
        var mapeditcontrols = $('#mapeditcontrols');
        mapeditcontrols.html(content).removeClass('loading');

        var redirect = mapeditcontrols.find('form[name=redirect]');
        if (redirect.length) {
            redirect.submit();
            return;
        }

        redirect = $('span[data-redirect]');
        if (redirect.length) {
            editor.sidebar_get(redirect.attr('data-redirect').replace('LEVEL', editor._level));
            return;
        }

        editor._check_start_editing();
    },
    _sidebar_link_click: function(e) {
        // listener for link-clicks in the sidebar.
        e.preventDefault();
        var href = $(this).attr('href');
        if ($(this).is('[data-insert-level]')) {
            href = href.replace('LEVEL', editor._level);
        }
        editor.sidebar_get(href);
    },
    _sidebar_submit_btn_click: function(e) {
        // listener for submit-button-clicks in the sidebar, so the submit event will know which button submitted.
        $(this).closest('form').data('btn', $(this)).clearQueue().delay(300).queue(function() {
            $(this).data('button', null);
        });
    },
    _sidebar_submit: function(e) {
        // listener for form submits in the sidebar.
        if ($(this).attr('name') == 'redirect') return;
        e.preventDefault();
        editor._sidebar_unload();
        var data = $(this).serialize();
        var btn = $(this).data('btn');
        if (btn !== undefined && btn !== null && $(btn).is('[name]')) {
            data += '&'+$('<input>').attr('name', $(btn).attr('name')).val($(btn).val()).serialize();
        }
        var action = $(this).attr('action');
        $.post(action, data, editor._sidebar_loaded);
    }
};


if ($('#mapeditcontrols').length) {
    editor.init();
}
