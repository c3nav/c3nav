(function () {
    if(L.Browser.chrome && !('ontouchstart' in window)) {
        L.Browser.pointer = false;
        L.Browser.touch = false;
    }
}());


editor = {
    options: {
		position: 'bottomright'
	},

    init: function () {
        // Init Map
        editor.map = L.map('map', {
            renderer: L.svg({ padding: 2 }),
            zoom: 2,
            maxZoom: 10,
            minZoom: 1,
            crs: L.CRS.Simple,
            editable: true,
            closePopupOnClick: false
        });
        editor.map.on('click', function () {
            editor.map.doubleClickZoom.enable();
        });
        window.onbeforeunload = editor._onbeforeunload;

        L.control.scale({imperial: false}).addTo(editor.map);

        $('#show_map').click(function(e) {
            e.preventDefault();
            $('body').addClass('show-map');
        });
        $('#show_details').click(function(e) {
            e.preventDefault();
            $('body').removeClass('show-map');
        });

        editor._level_control = new LevelControl().addTo(editor.map);
        editor._sublevel_control = new LevelControl({addClasses: 'leaflet-control-sublevels'}).addTo(editor.map);

        editor._level_control_container = $(editor._level_control._container);
        editor._sublevel_control_container = $(editor._sublevel_control._container);

        editor.init_geometries();
    },
    _onbeforeunload: function(e) {
        if ($('#sidebar').find('[data-onbeforeunload]').length) {
            e.returnValue = true;
        }
    },

    // sources
    sources: {},
    get_sources: function () {
        // load sources
        editor._sources_control = L.control.layers([], [], {autoZIndex: true});

        $.getJSON('/api/sources/', function (sources) {
            var source;
            for (var i = 0; i < sources.length; i++) {
                source = sources[i];
                editor.sources[source.id] = source;
                source.layer = L.imageOverlay('/api/sources/'+source.id+'/image/', source.bounds, {opacity: 0.3});
                editor._sources_control.addOverlay(source.layer, source.name);
            }
            if (sources.length) editor._sources_control.addTo(editor.map);
        });
    },

    // sidebar
    _last_non_modal_path: null,
    _last_graph_path: null,
    get_location_path: function () {
        return window.location.pathname + window.location.search;
    },
    init_sidebar: function() {
        // init the sidebar. sed listeners for form submits and link clicks
        $('#sidebar').find('.content').on('click', 'a[href]', editor._sidebar_link_click)
                                      .on('click', 'button[type=submit]', editor._sidebar_submit_btn_click)
                                      .on('submit', 'form', editor._sidebar_submit);
        $('nav.navbar').on('click', 'a[href]', editor._sidebar_link_click);
        var location_path = editor.get_location_path();
        editor._sidebar_loaded();
        history.replaceState({}, '', location_path);
        window.onpopstate = function() {
            editor.sidebar_get(editor.get_location_path(), true);
        };
    },
    sidebar_get: function(location, no_push) {
        // load a new page into the sidebar using a GET request
        if (!no_push) history.pushState({}, '', location);
        editor._sidebar_unload();
        $.get(location, editor._sidebar_loaded).fail(editor._sidebar_error);
    },
    _sidebar_unload: function() {
        // unload the sidebar. called on sidebar_get and form submit.
        editor._level_control.disable();
        editor._sublevel_control.disable();
        $('#sidebar').addClass('loading').find('.content').html('');
        editor._cancel_editing();
    },
    _fill_level_control: function (level_control, level_list) {
        var levels = level_list.find('a');
        if (levels.length) {
            var current;
            for (var i = 0; i < levels.length; i++) {
                var level = $(levels[i]);
                level_control.addLevel(level.attr('data-id'), level.text(), level.attr('href'), level.is('.current'));

            }
            if (levels.length > 1) {
                level_control.enable();
            } else {
                level_control.disable();
            }
            level_control.show()
        } else {
            level_control.hide();
        }
        level_control.current_id = parseInt(level_list.attr('data-current-id'));
    },
    _in_modal: false,
    _sidebar_loaded: function(data) {
        // sidebar was loaded. load the content. check if there are any redirects. call _check_start_editing.
        var content = $('#sidebar').removeClass('loading').find('.content');
        if (data !== undefined) {
            content.html($(data));
        }

        var redirect = content.find('span[data-redirect]');
        if (redirect.length) {
            editor.sidebar_get(redirect.attr('data-redirect'));
            return;
        }

        var nav = content.find('.nav');
        if (nav.length) {
            $('#navbar-collapse').find('.nav').html(nav.html());
        }

        content.find('[data-toggle="tooltip"]').tooltip();

        var modal_close = content.find('[data-modal-close]');
        var is_modal = (modal_close.length > 0);
        editor._in_modal = is_modal;
        if (!is_modal) {
            editor._last_non_modal_path = editor.get_location_path();
        } else if (editor._last_non_modal_path !== null) {
            if (content.find('[data-close-modal-now]').length) {
                editor.sidebar_get(editor._last_non_modal_path);
                return;
            }
            modal_close.attr('href', editor._last_non_modal_path).show();
        } else {
            modal_close.remove();
        }

        var active_graph_node = content.find('[data-active-node]');
        if (!editor._active_graph_node_space_transfer && !editor._in_modal && editor._last_graph_path !== editor.get_location_path()) {
            editor._active_graph_node = null;
            editor._active_graph_node_space_transfer = null;
            editor._active_graph_node_html = null;
        }
        if (active_graph_node.length) {
            var active_graph_node_id = active_graph_node.attr('data-active-node');
            if (active_graph_node_id !== '') {
                if (active_graph_node_id === 'null') {
                    editor._active_graph_node = null;
                    editor._active_graph_node_space_transfer = null;
                    editor._active_graph_node_html = null;
                    active_graph_node.remove();
                } else {
                    editor._active_graph_node = active_graph_node_id;
                    editor._active_graph_node_space_transfer = active_graph_node.is('[data-space-transfer]');
                    editor._active_graph_node_html = active_graph_node.html();
                }
            } else if (editor._active_graph_node_html !== null) {
                active_graph_node.html(editor._active_graph_node_html);
            } else {
                active_graph_node.remove();
            }
        }
        if (editor._active_graph_node !== null) {
            content.find('#id_active_node').val(editor._active_graph_node);
        }

        var graph_editing = content.find('[data-graph-editing]');
        if (graph_editing.length) {
            graph_editing = graph_editing.attr('data-graph-editing');
            editor._graph_editing = true;
            editor._graph_creating = (graph_editing === 'edit-create-nodes' ||
                                      (graph_editing === 'edit-create-if-no-active-node' &&
                                       editor._active_graph_node === null) ||
                                      (graph_editing === 'edit-create-if-active-node' &&
                                       editor._active_graph_node !== null));
            editor._last_graph_path = editor.get_location_path();
        } else if (!editor._in_modal) {
            editor._last_graph_path = null;
        }

        editor._deactivate_graph_node_on_click = (content.find('[data-deactivate-node-on-click]').length > 0);

        var geometry_url = content.find('[data-geometry-url]');
        var $body = $('body');
        if (geometry_url.length) {
            geometry_url = geometry_url.attr('data-geometry-url');
            var highlight_type = content.find('[data-list]');
            var editing_id = content.find('[data-editing]');
            if (editor._next_zoom === null) {
                editor._next_zoom = !content.find('[data-nozoom]').length;
            }
            editor.load_geometries(
                geometry_url,
                (highlight_type.length ? highlight_type.attr('data-list') : null),
                (editing_id.length ? editing_id.attr('data-editing') : null)
            );
            $body.addClass('map-enabled');
            editor._level_control.clearLevels();
            editor._sublevel_control.clearLevels();

            editor._fill_level_control(editor._level_control, content.find('[data-levels]'));
            editor._fill_level_control(editor._sublevel_control, content.find('[data-sublevels]'));

            var level_control_offset = $(editor._level_control_container).position();
            var offset_parent = $(editor._level_control_container).offsetParent();
            $(editor._sublevel_control._container).css({
                bottom: offset_parent.outerHeight()-level_control_offset.top-editor._level_control_container.outerHeight()-parseInt(editor._level_control_container.css('margin-bottom')),
                right: offset_parent.outerWidth()-level_control_offset.left
            });
        } else {
            $body.removeClass('show-map');
            if (!is_modal) $body.removeClass('map-enabled');
            editor.reload_geometries();
            editor._level_control.hide();
            editor._sublevel_control.hide();
        }
    },
    _sidebar_error: function(data) {
        $('#sidebar').removeClass('loading').find('.content').html('<h3>Error '+data.status+'</h3>'+data.statusText);
        editor._level_control.hide();
        editor._sublevel_control.hide();
    },
    _sidebar_link_click: function(e) {
        // listener for link-clicks in the sidebar.
        e.preventDefault();
        if (editor._loading_geometry) return;
        if ($(this).attr('href') === '') return;
        if ($(this).is('[data-force-next-zoom]')) editor._next_zoom = true;
        editor.sidebar_get($(this).attr('href'));
    },
    _sidebar_submit_btn_click: function() {
        // listener for submit-button-clicks in the sidebar, so the submit event will know which button submitted.
        if (editor._loading_geometry) return;
        $(this).closest('form').data('btn', $(this)).clearQueue().delay(300).queue(function() {
            $(this).data('btn', null);
        });
    },
    _sidebar_submit: function(e) {
        // listener for form submits in the sidebar.
        e.preventDefault();
        if (editor._loading_geometry) return;
        var data = $(this).serialize();
        var btn = $(this).data('btn');
        if (btn !== undefined && btn !== null) {
            if ($(btn).is('[name]')) {
                data += '&' + $('<input>').attr('name', $(btn).attr('name')).val($(btn).val()).serialize();
            }
        }
        var action = $(this).attr('action');
        editor._sidebar_unload();
        if (editor._in_modal) {
            data += '&can_close_modal=' + ((editor._last_non_modal_path === null) ? '0' : '1');
        }
        $.post(action, data, editor._sidebar_loaded).fail(editor._sidebar_error);
    },

    // geometries
    geometrystyles: {},
    _loading_geometry: false,
    _geometries_layer: null,
    _highlight_layer: null,
    _highlight_type: null,
    _editing_id: null,
    _editing_layer: null,
    _bounds_layer: null,
    _highlight_geometries: {},
    _creating: false,
    _next_zoom: true,
    _graph_editing: false,
    _graph_creating: false,
    _active_graph_node: null,
    _active_graph_node_space_transfer: null,
    _active_graph_node_html: null,
    _deactivate_graph_node_on_click: false,
    init_geometries: function () {
        // init geometries and edit listeners
        editor._highlight_layer = L.layerGroup().addTo(editor.map);

        $('#sidebar').find('.content').on('mouseenter', '.itemtable tr[data-pk]', editor._hover_mapitem_row)
                                      .on('mouseleave', '.itemtable tr[data-pk]', editor._unhover_mapitem_row)
                                      .on('click', '.itemtable tr[data-pk] td:not(:last-child)', editor._click_mapitem_row);

        editor.map.on('editable:drawing:commit', editor._done_creating);
        editor.map.on('editable:editing', editor._update_editing);
        editor.map.on('editable:drawing:cancel', editor._canceled_creating);
        editor.map.on('editable:vertex:click', function () {
            editor.map.doubleClickZoom.disable();
        });
        editor.map.on('editable:vertex:drag', function (e) {
            e.vertex.setLatLng([Math.round(e.latlng.lat*100)/100, Math.round(e.latlng.lng*100)/100]);
        });
        editor.map.on('editable:drawing:click', function (e) {
            e.latlng.lat = Math.round(e.latlng.lat*100)/100;
            e.latlng.lng = Math.round(e.latlng.lng*100)/100;
        });
        editor.map.on('editable:vertex:ctrlclick editable:vertex:metakeyclick', function (e) {
            e.vertex.continue();
        });

        $.getJSON('/api/editor/geometrystyles/', function(geometrystyles) {
            editor.geometrystyles = geometrystyles;
            $.getJSON('/api/editor/bounds/', function(bounds) {
                editor.map.setMaxBounds(bounds.bounds);
                editor.map.fitBounds(bounds.bounds, {padding: [30, 50]});
                editor.init_sidebar();
            });
        });
        editor.get_sources();
    },
    _last_geometry_url: null,
    load_geometries: function (geometry_url, highlight_type, editing_id) {
        // load geometries from url
        editor._last_geometry_url = geometry_url;
        editor._loading_geometry = true;
        editor._highlight_type = highlight_type;
        editor._highlight_geometries = {};
        editor._editing_id = editing_id;
        if (editor._editing_layer !== null) {
            editor._editing_layer.remove();
            editor._editing_layer = null;
        }
        editor._bounds_layer = null;

        $.getJSON(geometry_url, function(geometries) {
            editor.map.removeLayer(editor._highlight_layer);
            editor._highlight_layer.clearLayers();
            if (editor._geometries_layer !== null) {
                editor.map.removeLayer(editor._geometries_layer);
            }
            var feature = null, remove_feature = null;
            if (editor._editing_id !== null) {
                for (var i=0;i<geometries.length;i++) {
                    feature = geometries[i];
                    if (feature.properties.original_type !== undefined && feature.properties.original_type+'-'+String(feature.properties.original_id) === editor._editing_id) {
                        remove_feature = i;
                    } else if (feature.original_geometry !== undefined && feature.properties.type+'-'+String(feature.properties.id) === editor._editing_id) {
                        feature.geometry = feature.original_geometry;
                        break;
                    }
                }
            }
            if (remove_feature !== null) {
                geometries.splice(remove_feature, 1);
            }
            if (editor._last_graph_path === null) {
                geometries = geometries.filter(function(val) { return val.properties.type !== 'graphnode' && val.properties.type !== 'graphedge' })
            }
            editor._geometries_layer = L.geoJSON(geometries, {
                style: editor._get_geometry_style,
                pointToLayer: editor._point_to_layer,
                onEachFeature: editor._register_geojson_feature
            });
            editor._geometries_layer.addTo(editor.map);
            editor._highlight_layer.addTo(editor.map);
            editor._loading_geometry = false;
            if (editor._bounds_layer === null) editor._bounds_layer = editor._geometries_layer;
            if (editor._next_zoom) {
                editor.map.flyToBounds((editor._bounds_layer.getBounds !== undefined) ? editor._bounds_layer.getBounds() : [editor._bounds_layer.getLatLng(), editor._bounds_layer.getLatLng()], {
                    maxZoom: Math.max(4, editor.map.getZoom()),
                    duration: 0.5,
                    padding: [20, 20]
                });
            }
            editor._next_zoom = null;
            editor.map.doubleClickZoom.enable();

            editor._check_start_editing();
        });
    },
    reload_geometries: function () {
        if ($('body').is('.map-enabled') && editor._last_geometry_url !== null) {
            editor.load_geometries(editor._last_geometry_url);
        }
    },
    _line_draw_geometry_style: function(style) {
        style.stroke = true;
        style.opacity = 0.6;
        style.color = style.fillColor;
        style.weight = 5;
        return style;
    },
    _point_to_layer: function (feature, latlng) {
        return L.circle(latlng, {radius: 0.5});
    },
    _get_geometry_style: function (feature) {
        // style callback for GeoJSON loader
        var style = editor._get_mapitem_type_style(feature.properties.type);
        if (feature.properties.space_transfer) {
            style = editor._get_mapitem_type_style('graphnode__space_transfer');
        }
        if (editor._level_control.current_level_id === editor._sublevel_control.current_level_id) {
            if (editor._sublevel_control.level_ids.indexOf(feature.properties.level) >= 0 && editor._level_control.current_level_id !== feature.properties.level) {
                style.stroke = true;
                style.weight = 1;
                style.color = '#ffffff';
            }
        } else {
            if (feature.properties.level !== undefined && editor._sublevel_control.current_level_id !== feature.properties.level) {
                style.fillOpacity = 0.5;
            }
        }
        if (feature.properties.type === 'graphnode' && feature.properties.id === editor._active_graph_node) {
            style.stroke = true;
            style.weight = 3;
            style.color = '#ffff00';
        }
        if (feature.geometry.type === 'LineString') {
            style = editor._line_draw_geometry_style(style);
        }
        if (feature.properties.color !== undefined) {
            style.fillColor = feature.properties.color;
        }
        if (feature.properties.opacity !== undefined) {
            style.fillOpacity = feature.properties.opacity;
        }
        return style
    },
    _get_mapitem_type_style: function (mapitem_type) {
        // get styles for a specific mapitem
        return {
            stroke: false,
            fillColor: editor.geometrystyles[mapitem_type],
            fillOpacity: 1,
            smoothFactor: 0
        };
    },
    _register_geojson_feature: function (feature, layer) {
        // onEachFeature callback for GeoJSON loader – register all needed events
        if (feature.properties.type === editor._highlight_type) {
            var list_elem = $('#sidebar').find('[data-list] tr[data-pk='+String(feature.properties.id)+']');
            if (list_elem.length === 0) return;
            var highlight_layer = L.geoJSON(layer.feature, {
                style: function() {
                    return {
                        weight: 3,
                        opacity: 0,
                        fillOpacity: 0,
                        className: 'c3nav-highlight'
                    };
                },
                pointToLayer: editor._point_to_layer
            }).getLayers()[0].addTo(editor._highlight_layer);
            highlight_layer.list_elem = list_elem;
            editor._highlight_geometries[feature.properties.id] = highlight_layer;
            highlight_layer.on('mouseover', editor._hover_geometry_layer)
                 .on('mouseout', editor._unhover_geometry_layer)
                 .on('click', editor._click_geometry_layer)
                 .on('dblclick', editor._dblclick_geometry_layer);
        } else if (feature.properties.type+'-'+String(feature.properties.id) === editor._editing_id) {
            editor._editing_layer = layer;
            editor._bounds_layer = layer;
        } else if (feature.properties.bounds === true) {
            editor._bounds_layer = layer;
            if (editor._graph_creating) {
                var space_layer = L.geoJSON(layer.feature, {
                    style: function() {
                        return {
                            weight: 0,
                            opacity: 0,
                            fillOpacity: 0,
                            className: 'c3nav-graph-space'
                        };
                    }
                }).getLayers()[0].addTo(editor._highlight_layer);
                space_layer.on('click', editor._click_graph_current_space);
            }
        } else if (feature.properties.type === 'graphnode' && editor._graph_editing) {
            var node_layer = L.geoJSON(layer.feature, {
                style: function() {
                    return {
                        weight: 3,
                        opacity: 0,
                        fillOpacity: 0,
                        className: 'c3nav-graph-node'
                    };
                },
                pointToLayer: editor._point_to_layer
            }).getLayers()[0].addTo(editor._highlight_layer);
            node_layer.node_layer = layer;
            node_layer.on('mouseover', editor._hover_graph_item)
                .on('mouseout', editor._unhover_graph_item)
                .on('click', editor._click_graph_node);
        } else if (feature.properties.type === 'space' && editor._graph_editing && !editor._graph_creating) {
            var other_space_layer = L.geoJSON(layer.feature, {
                style: function() {
                    return {
                        weight: 3,
                        opacity: 0,
                        fillOpacity: 0,
                        className: 'c3nav-graph-other-space'
                    };
                },
                pointToLayer: editor._point_to_layer
            }).getLayers()[0].addTo(editor._highlight_layer);
            other_space_layer.on('mouseover', editor._hover_graph_item)
                .on('mouseout', editor._unhover_graph_item)
                .on('dblclick', editor._dblclick_graph_other_space);
        }
    },

    // hover and highlight geometries
    _hover_mapitem_row: function () {
        // hover callback for a itemtable row
        if (editor._loading_geometry) return;
        editor._highlight_geometry(parseInt($(this).attr('data-pk')));
    },
    _unhover_mapitem_row: function () {
        // unhover callback for a itemtable row
        if (editor._loading_geometry) return;
        editor._unhighlight_geometry(parseInt($(this).attr('data-pk')));
    },
    _click_mapitem_row: function () {
        if (editor._loading_geometry) return;
        var geometry = editor._highlight_geometries[parseInt($(this).parent().attr('data-pk'))];
        if (geometry !== undefined) {
            editor.map.flyToBounds(geometry.getBounds(), {
                maxZoom: 4,
                duration: 0.5,
                padding: [20, 20]
            });
        }
    },
    _hover_geometry_layer: function (e) {
        // hover callback for a geometry layer
        if (editor._loading_geometry) return;
        editor._highlight_geometry(e.target.feature.properties.id);
    },
    _unhover_geometry_layer: function (e) {
        // unhover callback for a geometry layer
        if (editor._loading_geometry) return;
        editor._unhighlight_geometry(e.target.feature.properties.id);
    },
    _click_geometry_layer: function (e) {
        // click callback for a geometry layer – scroll the corresponding itemtable row into view if it exists
        if (editor._loading_geometry) return;
        e.target.list_elem[0].scrollIntoView();
    },
    _dblclick_geometry_layer: function (e) {
        // dblclick callback for a geometry layer - edit this feature if the corresponding itemtable row exists
        if (editor._loading_geometry) return;
        e.target.list_elem.find('td:last-child a').click();
        e.target.list_elem.find('td:last-child a').click();
        editor.map.doubleClickZoom.disable();
    },
    _highlight_geometry: function(id) {
        // highlight a geometries layer and itemtable row if they both exist
        var geometry = editor._highlight_geometries[id];
        if (geometry !== undefined) {
            geometry.setStyle({
                color: '#FFFFDD',
                weight: 3,
                opacity: 1,
                fillOpacity: 0
            });
            geometry.list_elem.addClass('highlight');
        }
    },
    _unhighlight_geometry: function(id) {
        // unhighlight whatever is highlighted currently
        var geometry = editor._highlight_geometries[id];
        if (geometry !== undefined) {
            geometry.setStyle({
                weight: 3,
                opacity: 0,
                fillOpacity: 0
            });
            geometry.list_elem.removeClass('highlight');
        }
    },

    // graph events
    _hover_graph_item: function(e) {
        // hover callback for a graph node
        if (editor._loading_geometry) return;
        e.target.setStyle({
            color: '#FFFFDD',
            weight: 3,
            opacity: 1,
            fillOpacity: 0
        });
    },
    _unhover_graph_item: function(e) {
        // unhover callback for a graph node
        if (editor._loading_geometry) return;
        e.target.setStyle({
            weight: 3,
            opacity: 0,
            fillOpacity: 0
        });
    },
    _click_graph_current_space: function(e) {
        // click callback for a current graph space
        if (editor._loading_geometry) return;
        $('#id_clicked_position').val(JSON.stringify(L.marker(e.latlng).toGeoJSON().geometry)).closest('form').submit();
        editor.map.doubleClickZoom.disable();
    },
    _click_graph_node: function(e) {
        // click callback for a graph node
        if (editor._loading_geometry) return;
        if (editor._deactivate_graph_node_on_click && editor._active_graph_node === e.target.feature.properties.id) {
            e.target.node_layer.setStyle({
                stroke: false
            });
            e.target.setStyle({
                opacity: 0,
            });
            var sidebar = $('#sidebar');
            sidebar.find('[data-active-node]').remove();
            sidebar.find('#id_active_node').val('');
            editor._active_graph_node = null;
            editor._active_graph_node_space_transfer = null;
            editor._active_graph_node_html = null;
            return;
        }
        $('#id_clicked_node').val(e.target.feature.properties.id).closest('form').submit();
        editor.map.doubleClickZoom.disable();
    },
    _dblclick_graph_other_space: function(e) {
        // click callback for an other graph space
        if (editor._loading_geometry) return;
        editor._next_zoom = true;
        $('#id_goto_space').val(e.target.feature.properties.id).closest('form').submit();
        editor.map.doubleClickZoom.disable();
    },

    // edit and create geometries
    _check_start_editing: function() {
        // called on sidebar load. start editing or creating depending on how the sidebar may require it
        var sidebarcontent = $('#sidebar').find('.content');

        var geometry_field = sidebarcontent.find('input[name=geometry]');
        if (geometry_field.length) {
            var form = geometry_field.closest('form');
            if (editor._editing_layer !== null) {
                editor._editing_layer.enableEdit();
                if (editor._editing_layer.editor._resizeLatLng !== undefined) {
                    editor._editing_layer.editor._resizeLatLng.__vertex._icon.style.display = 'none';
                }
            } else if (form.is('[data-new]')) {
                // create new geometry
                var mapitem_type = form.attr('data-new');
                var options = editor._get_mapitem_type_style(mapitem_type);
                form.addClass('creation-lock');
                var geomtype = form.attr('data-geomtype');
                if (geomtype === 'polygon') {
                    editor.map.editTools.startPolygon(null, options);
                } else if (geomtype === 'polyline') {
                    options = editor._line_draw_geometry_style(options);
                    editor.map.editTools.startPolyline(null, options);
                } else if (geomtype === 'point') {
                    editor.map.editTools.startMarker(null, options);
                }
                editor._creating = true;
            }
        }
    },
    _cancel_editing: function() {
        // called on sidebar unload. cancel all editing and creating.
        if (editor._creating) {
            editor._creating = false;
            editor.map.editTools.stopDrawing();
        }
        editor._graph_editing = false;
        editor._graph_creating = false;
        if (editor._editing_layer !== null) {
            editor._editing_layer.disableEdit();
            editor._editing_layer = null;
        }
    },
    _canceled_creating: function (e) {
        // called after we canceled creating so we can remove the temporary layer.
        if (!editor._creating) {
            e.layer.remove();
        }
    },
    _done_creating: function(e) {
        // called when creating is completed (by clicking on the last point). fills in the form and switches to editing.
        if (editor._creating) {
            editor._creating = false;
            // return L.circle(latlng, {radius: 0.5});
            var layer = e.layer;
            if (e.layer._latlng !== undefined) {
                layer = L.circle(e.layer._latlng, e.layer.options);
                layer.setRadius(0.5);
                e.layer.remove();
            }
            editor._editing_layer = layer;
            editor._editing_layer.addTo(editor._geometries_layer);
            if (e.layer._latlng !== undefined) {
                layer.enableEdit();
                layer.editor._resizeLatLng.__vertex._icon.style.display = 'none';
            }
            editor._update_editing();
            $('#sidebar').find('.content').find('form.creation-lock').removeClass('creation-lock');
            $('#id_name').focus();
        }
    },
    _update_editing: function () {
        // called if the temporary drawing layer changes. if we are in editing mode (not creating), update the form.
        if (editor._editing_layer !== null) {
            $('#id_geometry').val(JSON.stringify(editor._editing_layer.toGeoJSON().geometry));
        }
    }
};


LevelControl = L.Control.extend({
    options: {
		position: 'bottomright',
        addClasses: ''
	},

	onAdd: function () {
		this._container = L.DomUtil.create('div', 'leaflet-control-levels leaflet-bar '+this.options.addClasses);
		this._levelButtons = [];
		//noinspection JSUnusedGlobalSymbols
        this.current_level_id = null;
		this.level_ids = [];
		this._disabled = true;
		this._expanded = false;
		this.hide();

		if (!L.Browser.android) {
            L.DomEvent.on(this._container, {
                mouseenter: this.expand,
                mouseleave: this.collapse
            }, this);
        }

        if (!L.Browser.touch) {
            L.DomEvent.on(this._container, 'focus', this.expand, this);
        }

        this._map.on('click', this.collapse, this);

		return this._container;
	},

	addLevel: function (id, title, href, current) {
        this.level_ids.push(parseInt(id));
		if (current) this.current_level_id = parseInt(id);

		var link = L.DomUtil.create('a', (current ? 'current' : ''), this._container);
		link.innerHTML = title;
		link.href = href;

		L.DomEvent
		    .on(link, 'mousedown dblclick', L.DomEvent.stopPropagation)
		    .on(link, 'click', this._levelClick, this);

        this._levelButtons.push(link);
		return link;
	},

    clearLevels: function() {
        this.current_level_id = null;
		this.level_ids = [];
        for (var i = 0; i < this._levelButtons.length; i++) {
            L.DomUtil.remove(this._levelButtons[i]);
        }
        this._levelButtons = [];
    },

    disable: function () {
        for (var i = 0; i < this._levelButtons.length; i++) {
            L.DomUtil.addClass(this._levelButtons[i], 'leaflet-disabled');
        }
        this.collapse();
        this._disabled = true;
    },

    enable: function () {
        for (var i = 0; i < this._levelButtons.length; i++) {
            L.DomUtil.removeClass(this._levelButtons[i], 'leaflet-disabled');
        }
        this._disabled = false;
    },

    hide: function () {
        this._container.style.display = 'none';
    },

    show: function () {
        this._container.style.display = '';
    },

    _levelClick: function (e) {
        e.preventDefault();
        e.stopPropagation();
        if (!this._expanded) {
            this.expand();
        } else if (!this._disabled) {
            $(e.target).addClass('current').siblings().removeClass('current');
            editor._next_zoom = false;
            editor.sidebar_get(e.target.href);
            this.collapse();
        }
	},

    expand: function () {
        if (this._disabled) return;
        this._expanded = true;
		L.DomUtil.addClass(this._container, 'leaflet-control-levels-expanded');
		return this;
	},

	collapse: function () {
        this._expanded = false;
		L.DomUtil.removeClass(this._container, 'leaflet-control-levels-expanded');
		return this;
	}
});


if ($('#sidebar').length) {
    editor.init();
}
