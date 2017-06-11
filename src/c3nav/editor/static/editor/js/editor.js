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

        editor._section_control = new SectionControl().addTo(editor.map);
        editor._subsection_control = new SectionControl({addClasses: 'leaflet-control-subsections'}).addTo(editor.map);

        editor._section_control_container = $(editor._section_control._container);
        editor._subsection_control_container = $(editor._subsection_control._container);

        editor.init_geometries();
    },
    _onbeforeunload: function(e) {
        if ($('#sidebar').find('[data-onbeforeunload]').length) {
            e.returnValue = true;
        }
    },

    // sources
    sources: {},
    get_sources: function (init_sidebar) {
        // load sources
        editor._sources_control = L.control.layers([], [], {autoZIndex: true}).addTo(editor.map);

        $.getJSON('/api/sources/', function (sources) {
            var bounds = [[0, 0], [0, 0]];
            var source;
            for (var i = 0; i < sources.length; i++) {
                source = sources[i];
                editor.sources[source.id] = source;
                source.layer = L.imageOverlay('/api/sources/'+source.id+'/image/', source.bounds, {opacity: 0.3});
                editor._sources_control.addOverlay(source.layer, source.name);
                bounds[0][0] = Math.min(source.bounds[0][0], bounds[0][0]);
                bounds[0][1] = Math.min(source.bounds[0][1], bounds[0][1]);
                bounds[1][0] = Math.max(source.bounds[1][0], bounds[1][0]);
                bounds[1][1] = Math.max(source.bounds[1][1], bounds[1][1]);
            }
            editor.map.setMaxBounds(bounds);
            if (init_sidebar) {
                editor.map.fitBounds(bounds, {padding: [30, 50]});
                editor.init_sidebar();
            }
        });
    },

    // sidebar
    get_location_path: function () {
        return window.location.pathname + window.location.search;
    },
    init_sidebar: function() {
        // init the sidebar. sed listeners for form submits and link clicks
        $('#sidebar').find('.content').on('click', 'a[href]', editor._sidebar_link_click)
                                      .on('click', 'button[type=submit]', editor._sidebar_submit_btn_click)
                                      .on('submit', 'form', editor._sidebar_submit);
        var location_path = editor.get_location_path();
        editor._sidebar_loaded();
        history.replaceState({}, '', location_path);
        window.onpopstate = function() {
            editor.sidebar_get(editor.get_location_path());
        };
    },
    sidebar_get: function(location) {
        // load a new page into the sidebar using a GET request
        if ($('#sidebar').find('.content').html() !== '') {
            history.pushState({}, '', location);
        }
        editor._sidebar_unload();
        $.get(location, editor._sidebar_loaded).fail(editor._sidebar_error);
    },
    _sidebar_unload: function() {
        // unload the sidebar. called on sidebar_get and form submit.
        editor._section_control.disable();
        editor._subsection_control.disable();
        $('#sidebar').addClass('loading').find('.content').html('');
        editor._cancel_editing();
    },
    _fill_section_control: function (section_control, sections) {
        if (sections.length) {
            for (var i = 0; i < sections.length; i++) {
                var section = $(sections[i]);
                section_control.addSection(section.text(), section.attr('href'), section.is('.current'));
            }
            if (sections.length > 1) {
                section_control.enable();
            } else {
                section_control.disable();
            }
            section_control.show()
        } else {
            section_control.hide();
        }
    },
    _sidebar_loaded: function(data) {
        // sidebar was loaded. load the content. check if there are any redirects. call _check_start_editing.
        var content = $('#sidebar').removeClass('loading').find('.content');;
        if (data !== undefined) {
            content.html($(data));
        }

        var redirect = content.find('span[data-redirect]');
        if (redirect.length) {
            editor.sidebar_get(redirect.attr('data-redirect'));
            return;
        }

        var geometry_url = content.find('[data-geometry-url]');
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
            $('body').addClass('map-enabled');
            editor._section_control.clearSections();
            editor._subsection_control.clearSections();

            editor._fill_section_control(editor._section_control, content.find('[data-sections] a'));
            editor._fill_section_control(editor._subsection_control, content.find('[data-subsections] a'));

            var section_control_offset = $(editor._section_control_container).position();
            var offset_parent = $(editor._section_control_container).offsetParent();
            $(editor._subsection_control._container).css({
                bottom: offset_parent.height()-section_control_offset.top-editor._section_control_container.height()-parseInt(editor._section_control_container.css('margin-bottom')),
                right: offset_parent.width()-section_control_offset.left
            });
        } else {
            $('body').removeClass('map-enabled').removeClass('show-map');
            editor._section_control.hide();
            editor._subsection_control.hide();
        }
    },
    _sidebar_error: function(data) {
        $('#sidebar').removeClass('loading').find('.content').html('<h3>Error '+data.status+'</h3>'+data.statusText);
        editor._section_control.hide();
        editor._subsection_control.hide();
    },
    _sidebar_link_click: function(e) {
        // listener for link-clicks in the sidebar.
        e.preventDefault();
        if (editor._loading_geometry) return;
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
            e.vertex.setLatLng([(Math.round(e.latlng.lat*100)/100).toFixed(2),
                                (Math.round(e.latlng.lng*100)/100).toFixed(2)]);
        });
        editor.map.on('editable:drawing:click', function (e) {
            e.latlng.lat = (Math.round(e.latlng.lat*100)/100).toFixed(2);
            e.latlng.lng = (Math.round(e.latlng.lng*100)/100).toFixed(2);
        });
        editor.map.on('editable:vertex:ctrlclick editable:vertex:metakeyclick', function (e) {
            e.vertex.continue();
        });

        $.getJSON('/api/editor/geometrystyles/', function(geometrystyles) {
            editor.geometrystyles = geometrystyles;
            editor.get_sources(true);
        });
    },
    load_geometries: function (geometry_url, highlight_type, editing_id) {
        // load geometries from url
        editor._loading_geometry = true;
        editor._highlight_type = highlight_type;
        editor._highlight_geometries = {};
        editor._editing_id = editing_id;
        if (editor._editing_layer !== null) {
            editor._editing_layer.remove();
            editor._editing_layer = null;
        }
        editor._bounds_layer = null;

        editor.map.removeLayer(editor._highlight_layer);
        editor._highlight_layer.clearLayers();
        $.getJSON(geometry_url, function(geometries) {
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
            editor._geometries_layer = L.geoJSON(geometries, {
                style: editor._get_geometry_style,
                onEachFeature: editor._register_geojson_feature
            });
            editor._geometries_layer.addTo(editor.map);
            editor._highlight_layer.addTo(editor.map);
            editor._loading_geometry = false;
            if (editor._bounds_layer === null) editor._bounds_layer = editor._geometries_layer;
            if (editor._next_zoom) {
                editor.map.flyToBounds((editor._bounds_layer.getBounds !== undefined) ? editor._bounds_layer.getBounds() : [editor._bounds_layer.getLatLng(), editor._bounds_layer.getLatLng()], {
                    maxZoom: 4,
                    duration: 0.5,
                    padding: [20, 20]
                });
            }
            editor._next_zoom = null;

            editor._check_start_editing();
        });
    },
    _line_draw_geometry_style: function(style) {
        style.stroke = true;
        style.opacity = 0.6;
        style.color = style.fillColor;
        style.weight = 5;
        return style;
    },
    _get_geometry_style: function (feature) {
        // style callback for GeoJSON loader
        var style = editor._get_mapitem_type_style(feature.properties.type);
        if (feature.properties.layer === 'upper') {
            style.stroke = true;
            style.weight = 1;
            style.color = '#ffffff';
        }
        if (feature.geometry.type === 'LineString') {
            style = editor._line_draw_geometry_style(style);
        }
        if (feature.properties.color !== undefined) {
            style.fillColor = feature.properties.color;
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
            if (list_elem.length == 0) return;
            highlight_layer = L.geoJSON(layer.feature, {
                style: function() {
                    return {
                        weight: 3,
                        opacity: 0,
                        fillOpacity: 0,
                        className: 'c3nav-highlight'
                    };
                }
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
            layer.on('click', editor._click_editing_layer);
        } else if (feature.properties.bounds === true) {
            editor._bounds_layer = layer;
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
                fillOpacity: 0,
                className: 'c3nav-highlight'
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
                fillOpacity: 0,
                className: 'c3nav-highlight'
            });
            geometry.list_elem.removeClass('highlight');
        }
    },

    // edit and create geometries
    _check_start_editing: function() {
        // called on sidebar load. start editing or creating depending on how the sidebar may require it
        var sidebarcontent = $('#sidebar').find('.content');
        var geometry_field = sidebarcontent.find('input[name=geometry]');
        if (geometry_field.length) {
            var form = geometry_field.closest('form');
            var mapitem_type = form.attr('data-new');
            if (editor._editing_layer !== null) {
                editor._editing_layer.enableEdit();
            } else if (form.is('[data-new]')) {
                // create new geometry
                var options = editor._get_mapitem_type_style(mapitem_type);
                if (geometry_field.val() === '') {
                    form.addClass('creation-lock');
                    var geomtype = form.attr('data-geomtype');
                    if (geomtype === 'polygon') {
                        editor.map.editTools.startPolygon(null, options);
                    } else if (geomtype === 'polyline') {
                        options = editor._line_draw_geometry_style(options);
                        editor.map.editTools.startPolyline(null, options);
                    }
                    editor._creating = true;
                } else {
                    editor._editing_layer = L.geoJSON({
                        "type": "Feature",
                        "geometry": JSON.parse(geometry_field.val())
                    }, {
                        style: function() {
                            return options;
                        }
                    }).getLayers()[0].addTo(editor.map);
                    editor._editing_layer.enableEdit();
                }
            }
        }
    },
    _cancel_editing: function() {
        // called on sidebar unload. cancel all editing and creating.
        if (editor._creating) {
            editor._creating = false;
            editor.map.editTools.stopDrawing();
        }
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
    _click_editing_layer: function(e) {
        // click callback for a currently edited layer. create a hole on ctrl+click.
        if ((e.originalEvent.ctrlKey || e.originalEvent.metaKey)) {
            if (e.target instanceof L.Polygon) {
                this.editor.newHole(e.latlng);
            }
        }
    },
    _done_creating: function(e) {
        // called when creating is completed (by clicking on the last point). fills in the form and switches to editing.
        if (editor._creating) {
            editor._creating = false;
            editor._editing_layer = e.layer;
            editor._editing_layer.addTo(editor._geometries_layer);
            editor._editing_layer.on('click', editor._click_editing_layer);
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


SectionControl = L.Control.extend({
    options: {
		position: 'bottomright',
        addClasses: ''
	},

	onAdd: function () {
		this._container = L.DomUtil.create('div', 'leaflet-control-sections leaflet-bar '+this.options.addClasses);
		this._sectionButtons = [];
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

	addSection: function (title, href, current) {
		var link = L.DomUtil.create('a', (current ? 'current' : ''), this._container);
		link.innerHTML = title;
		link.href = href;

		L.DomEvent
		    .on(link, 'mousedown dblclick', L.DomEvent.stopPropagation)
		    .on(link, 'click', this._sectionClick, this);

        this._sectionButtons.push(link);
		return link;
	},

    clearSections: function() {
        for (var i = 0; i < this._sectionButtons.length; i++) {
            L.DomUtil.remove(this._sectionButtons[i]);
        }
        this._sectionButtons = [];
    },

    disable: function () {
        for (var i = 0; i < this._sectionButtons.length; i++) {
            L.DomUtil.addClass(this._sectionButtons[i], 'leaflet-disabled');
        }
        this.collapse();
        this._disabled = true;
    },

    enable: function () {
        for (var i = 0; i < this._sectionButtons.length; i++) {
            L.DomUtil.removeClass(this._sectionButtons[i], 'leaflet-disabled');
        }
        this._disabled = false;
    },

    hide: function () {
        this._container.style.display = 'none';
    },

    show: function () {
        this._container.style.display = '';
    },

    _sectionClick: function (e) {
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
		L.DomUtil.addClass(this._container, 'leaflet-control-sections-expanded');
		return this;
	},

	collapse: function () {
        this._expanded = false;
		L.DomUtil.removeClass(this._container, 'leaflet-control-sections-expanded');
		return this;
	}
});


if ($('#sidebar').length) {
    editor.init();
}
