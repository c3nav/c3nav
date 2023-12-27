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
            minZoom: -5,
            crs: L.CRS.Simple,
            editable: true,
            zoomSnap: 0
        });
        if (L.Browser.chrome && !('ontouchstart' in window)) {
            $('.leaflet-touch').removeClass('leaflet-touch');
            L.Browser.touch = false;
        }
        editor.map.on('click', function () {
            editor.map.doubleClickZoom.enable();
        });

        let $map = $('#map');
        if ($map.is('[data-x][data-y]')) {
            L.marker(
                L.GeoJSON.coordsToLatLng([
                    parseFloat($map.attr('data-x')),
                    parseFloat($map.attr('data-y'))
                ]),
            ).addTo(editor.map);
        }

        if (window.mobileclient) {
            var $body = $('body');
            $body.addClass('mobileclient');
            if ($body.is('[data-user-data]')) {
                editor._inform_mobile_client($body);
            }
        }

        /*
         * Fix scroll wheel zoom on precise scrolling devices
         */
        var originalPerformZoom = L.Map.ScrollWheelZoom.prototype._performZoom;
        L.Map.ScrollWheelZoom.include({
            _performZoom: function () {
                if (this._delta) this._delta = (this._delta > 0) ? Math.max(this._delta, 60) : Math.min(this._delta, -60);
                originalPerformZoom.call(this);
            }
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
        editor.init_wificollector();
    },
    _inform_mobile_client: function(elem) {
        if (!window.mobileclient || !elem.length) return;
        var data = JSON.parse(elem.attr('data-user-data'));
        data.changes_count_display = elem.attr('data-count-display');
        data.direct_editing = elem.is('[data-direct-editing]');
        data.has_changeset = elem.is('[data-has-changeset]');
        mobileclient.setUserData(JSON.stringify(data));
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
        editor._sources_control = L.control.layers([], [], { autoZIndex: false });

        c3nav_api.get('mapdata/sources')
            .then(async sources => {
                for (var i = 0; i < sources.length; i++) {
                    const source = sources[i];
                    editor.sources[source.id] = source;
                    const bounds = L.GeoJSON.coordsToLatLngs(source.bounds);
                    options = {opacity: 0.3};
                    source.layer = L.imageOverlay('/editor/sourceimage/' + source.name, bounds, options);
                    const is_svg = source.name.endsWith('.svg');
                    editor._sources_control.addOverlay(source.layer, is_svg ? `${source.name} (image overlay)` : source.name);

                    if (is_svg) {
                        source.svg_el = document.createElementNS("http://www.w3.org/2000/svg", "svg");
                        source.svg_el.setAttribute('xmlns', "http://www.w3.org/2000/svg");
                        source.svg_layer = L.svgOverlay(source.svg_el, bounds, options);
                        editor._sources_control.addOverlay(source.svg_layer, `${source.name} (svg overlay)`);
                        source.svg_layer.on('add', function () {
                            if (source.svg_promise) return;
                            source.svg_promise = fetch(`/editor/sourceimage/${source.name}`)
                                .then(r => {
                                    if (!r.ok) {
                                        throw 'could not load source svg';
                                    }
                                    return r.text();
                                })
                                .then(src => {
                                    const root = (new DOMParser).parseFromString(src, 'image/svg+xml').documentElement;
                                    for (const attr of root.attributes) {
                                        source.svg_el.attributes.setNamedItem(attr.cloneNode(true));
                                    }
                                    source.svg_el.replaceChildren(...root.children);
                                });
                        })
                    }


                }
                if (sources.length) editor._sources_control.addTo(editor.map);
            })
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

        if (editor._source_image_layer) {
            editor._source_image_layer.remove();
            editor._source_image_layer = null;
        }

        if (editor._fixed_point_layer) {
            editor._fixed_point_layer.remove();
            editor._fixed_point_layer = null;
        }

        if (window.mobileclient && mobileclient.wificollectorStop && $('#sidebar').find('.wificollector.running').length) {
            mobileclient.wificollectorStop();
        }

        $('#sidebar').addClass('loading').find('.content').html('');
        editor._cancel_editing();
    },
    _fill_level_control: function (level_control, level_list) {
        var levels = level_list.find('a');
        if (levels.length) {
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
            var doc = (new DOMParser).parseFromString(data, 'text/html');
            content[0].replaceChildren(...doc.body.children);
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

        editor._inform_mobile_client(content.find('[data-user-data]'));

        var group;
        if (content.find('[name=fixed_x]').length) {
            $('[name=name]').change(editor._source_name_selected).change();
            if (!content.find('[data-new]').length) {
                var bounds = [[parseFloat(content.find('[name=left]').val()), parseFloat(content.find('[name=bottom]').val())], [parseFloat(content.find('[name=right]').val()), parseFloat(content.find('[name=top]').val())]];
                bounds = L.GeoJSON.coordsToLatLngs(bounds);
                editor.map.fitBounds(bounds, {padding: [30, 50]});
            }

            group = $('<div class="form-group-group source-wizard">');
            group.insertBefore(content.find('[name=fixed_x]').closest('.form-group'));
            group.append(content.find('[name=fixed_x]').closest('.form-group'));
            group.append(content.find('[name=fixed_y]').closest('.form-group'));

            content.find('[name=fixed_x], [name=fixed_y]').change(editor._fixed_point_changed).change();
            content.find('[name=copy_from]').change(editor._copy_from_changed);

            group = $('<div class="form-group-group source-wizard">');
            group.insertBefore(content.find('[name=scale_x]').closest('.form-group'));
            group.append(content.find('[name=scale_x]').closest('.form-group'));
            group.append(content.find('[name=scale_y]').closest('.form-group'));

            content.find('[name=left], [name=bottom], [name=right], [name=top]').change(editor._source_image_bounds_changed);
            content.find('[name=scale_x], [name=scale_y]').change(editor._source_image_scale_changed);
            content.find('[name=left], [name=bottom], [name=right], [name=top]').each(function() { $(this).data('oldval', $(this).val()); });

            content.find('[name=lock_aspect], [name=lock_scale]').closest('.form-group').addClass('source-wizard');

            var source_width = (parseFloat(content.find('[name=right]').val()) || 0) - (parseFloat(content.find('[name=left]').val()) || 0),
                source_height = (parseFloat(content.find('[name=top]').val()) || 0) - (parseFloat(content.find('[name=bottom]').val()) || 0);
            editor._source_aspect_ratio = source_width/(source_height || 1);
        }
        if (content.find('[name=left]').length) {
            group = $('<div class="form-group-group">');
            group.insertBefore(content.find('[name=left]').closest('.form-group'));
            group.append(content.find('[name=left]').closest('.form-group'));
            group.append(content.find('[name=top]').closest('.form-group'));
            group = $('<div class="form-group-group">');
            group.insertBefore(content.find('[name=right]').closest('.form-group'));
            group.append(content.find('[name=right]').closest('.form-group'));
            group.append(content.find('[name=bottom]').closest('.form-group'));
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
        if (active_graph_node.length) {
            var active_graph_node_id = active_graph_node.attr('data-active-node');
            if (active_graph_node_id !== '') {
                if (active_graph_node_id === 'null') {
                    editor._active_graph_node = null;
                    editor._active_graph_node_html = null;
                    active_graph_node.remove();
                } else {
                    editor._active_graph_node = parseInt(active_graph_node_id) || active_graph_node_id;
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
            editor._graph_editing = true;
            editor._graph_creating = (content.find('[data-graph-create-nodes]').length > 0);
            editor._last_graph_path = editor.get_location_path();
        } else if (!editor._in_modal) {
            editor._last_graph_path = null;
        }

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

        var data_field = $('form [name=data]');
        if (data_field.length) {
            data_field.hide();
            var collector = $($('body .wificollector')[0].outerHTML);
            var existing_data = [];
            if (data_field.val()) {
                existing_data = JSON.parse(data_field.val());
            }
            if (existing_data.length > 0) {
                collector.removeClass('empty').addClass('done').find('.count').text(existing_data.length);
            } else {
                data_field.closest('form').addClass('scan-lock');
            }
            data_field.after(collector);
        }
    },
    _sidebar_error: function(data) {
        $('#sidebar').removeClass('loading').find('.content').html('<h3>Error '+data.status+'</h3>'+data.statusText);
        editor._level_control.hide();
        editor._sublevel_control.hide();
    },
    _sidebar_link_click: function(e) {
        // listener for link-clicks in the sidebar.
        var href = $(this).attr('href');
        if (href && !href.startsWith('/editor/')) return;
        e.preventDefault();
        if (editor._loading_geometry) return;
        if (!href) return;
        if ($(this).is('[data-force-next-zoom]')) editor._next_zoom = true;
        if ($(this).is('[data-no-next-zoom]')) editor._next_zoom = false;
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
        if (editor._loading_geometry || $(this).is('.creation-lock') || $(this).is('.scan-lock')) return;
        var data = $(this).serialize();
        var btn = $(this).data('btn');
        if (btn !== undefined && btn !== null) {
            if ($(btn).is('[name]')) {
                var name = $(btn).attr('name');
                data += '&' + $('<input>').attr('name', name).val($(btn).val()).serialize();
                if (name === 'delete_confirm') {
                    editor._active_graph_node = null;
                    editor._active_graph_node_html = null;
                }
            }
        }
        var action = $(this).attr('action');
        editor._sidebar_unload();
        if (editor._in_modal) {
            data += '&can_close_modal=' + ((editor._last_non_modal_path === null) ? '0' : '1');
        }
        $.post(action, data, editor._sidebar_loaded).fail(editor._sidebar_error);
    },

    _source_image_orig_width: 0,
    _source_image_orig_height: 0,
    _source_image_aspect_ratio: 0,
    _source_image_untouched: 0,
    _source_image_layer: null,
    _source_name_selected: function() {
        if (editor._source_image_layer) {
            editor._source_image_layer.remove();
            editor._source_image_layer = null;
        }
        // noinspection HtmlRequiredAltAttribute
        $('<img src="/editor/sourceimage/'+$(this).val()+'">').on('load', editor._source_name_selected_ajax_callback);
        $('#sidebar form').removeClass('show-source-wizard');
        $('body').removeClass('map-enabled');
    },
    _source_name_selected_ajax_callback: function() {
        if ($(this).attr('src').endsWith($('#sidebar [name=name]').val())) {
            $('#sidebar form').addClass('show-source-wizard');
            $(this).appendTo('body').hide();
            editor._source_image_orig_width = $(this).width();
            editor._source_image_orig_height = $(this).height();
            $(this).remove();
            $('body').addClass('map-enabled');
            var content = $('#sidebar');
            if (content.find('[data-new]').length || isNaN(parseFloat(content.find('[name=right]').val())) || isNaN(parseFloat(content.find('[name=left]').val())) || isNaN(parseFloat(content.find('[name=top]').val())) || isNaN(parseFloat(content.find('[name=bottom]').val()))) {
                editor._source_aspect_ratio = $(this).width()/$(this).height();
                content.find('[name=left]').val(0).data('oldval', 0);
                content.find('[name=bottom]').val(0).data('oldval', 0);
                var factor = 1;
                while(factor < 1000 && (editor._source_image_orig_width/factor)>1500) {
                    factor *= 10;
                }
                var width = (editor._source_image_orig_width/factor).toFixed(2),
                    height = (editor._source_image_orig_height/factor).toFixed(2);
                content.find('[name=right]').val(width).data('oldval', width);
                content.find('[name=top]').val(height).data('oldval', height);
                content.find('[name=scale_x]').val(1/factor);
                content.find('[name=scale_y]').val(1/factor);
            } else {
                editor._source_image_calculate_scale();
            }
            editor._source_image_repositioned();
        }
    },
    _source_image_repositioned: function() {
        var content = $('#sidebar');
        if (isNaN(parseFloat(content.find('[name=right]').val())) || isNaN(parseFloat(content.find('[name=left]').val())) || isNaN(parseFloat(content.find('[name=top]').val())) || isNaN(parseFloat(content.find('[name=bottom]').val()))) {
            return;
        }
        var bounds = [[parseFloat(content.find('[name=left]').val()), parseFloat(content.find('[name=bottom]').val())], [parseFloat(content.find('[name=right]').val()), parseFloat(content.find('[name=top]').val())]];
        bounds = L.GeoJSON.coordsToLatLngs(bounds);

        editor._set_max_bounds(bounds);
        if (editor._source_image_layer) {
            editor._source_image_layer.setBounds(bounds)
        } else {
            editor._source_image_layer = L.imageOverlay('/editor/sourceimage/'+content.find('[name=name]').val(), bounds, {opacity: 0.3, zIndex: 10000});
            editor._source_image_layer.addTo(editor.map);
            if (content.find('[data-new]').length) {
                editor.map.fitBounds(bounds, {padding: [30, 50]});
            }
        }
    },
    _source_image_calculate_scale: function() {
        var content = $('#sidebar');
        var source_width = parseFloat(content.find('[name=right]').val()) - parseFloat(content.find('[name=left]').val()),
            source_height = parseFloat(content.find('[name=top]').val()) - parseFloat(content.find('[name=bottom]').val());
        if (isNaN(source_width) || isNaN(source_height)) return;
        var scale_x = (source_width/editor._source_image_orig_width).toFixed(3),
            scale_y = (source_height/editor._source_image_orig_height).toFixed(3);
        content.find('[name=scale_x]').val(scale_x);
        content.find('[name=scale_y]').val(scale_y);
        if (scale_x !== scale_y) {
            content.find('[name=lock_aspect]').prop('checked', false);
        }
    },
    _source_image_bounds_changed: function() {
        var content = $('#sidebar'),
            lock_scale = content.find('[name=lock_scale]').prop('checked'),
            oldval = $(this).data('oldval'),
            newval = $(this).val(),
            diff = parseFloat(newval)-parseFloat(oldval);
        $(this).data('oldval', newval);
        if (lock_scale) {
            if (!isNaN(diff)) {
                var other_field_name = {left: 'right', right: 'left', top: 'bottom', bottom: 'top'}[$(this).attr('name')],
                    other_field = content.find('[name='+other_field_name+']'),
                    other_val = parseFloat(other_field.val());
                if (!isNaN(other_val)) {
                    other_field.val((other_val+diff).toFixed(2)).data('oldval', other_val);
                }
            }
        } else {
            editor._source_image_calculate_scale();
        }
        editor._source_image_repositioned();
    },
    _source_image_scale_changed: function() {
        var content = $('#sidebar'),
            lock_aspect = content.find('[name=lock_scale]').prop('checked');
        if (lock_aspect) {
            var other_field_name = {scale_x: 'scale_y', scale_y: 'scale_x'}[$(this).attr('name')],
                other_field = content.find('[name='+other_field_name+']');
            other_field.val($(this).val());
        }
        var f_scale_x = content.find('[name=scale_x]'),
            f_scale_y = content.find('[name=scale_y]'),
            scale_x = f_scale_x.val(),
            scale_y = f_scale_y.val(),
            fixed_x = parseFloat(content.find('[name=fixed_x]').val()),
            fixed_y = parseFloat(content.find('[name=fixed_y]').val()),
            left = parseFloat(content.find('[name=left]').val()),
            bottom = parseFloat(content.find('[name=bottom]').val()),
            right = parseFloat(content.find('[name=right]').val()),
            top = parseFloat(content.find('[name=top]').val());

        scale_x = parseFloat(scale_x);
        scale_y = parseFloat(scale_y);

        if (isNaN(scale_x) || isNaN(scale_y) || isNaN(fixed_x) || isNaN(fixed_y) || isNaN(left) || isNaN(bottom) || isNaN(right) || isNaN(top)) return;

        var fixed_x_relative = (fixed_x-left)/(right-left),
            fixed_y_relative = (fixed_y-bottom)/(top-bottom),
            width = editor._source_image_orig_width*scale_x,
            height = editor._source_image_orig_height*scale_y;
        left = fixed_x-(width*fixed_x_relative);
        bottom = fixed_y-(height*fixed_y_relative);
        right = left+width;
        top = bottom+height;

        left = left.toFixed(2);
        bottom = bottom.toFixed(2);
        right = right.toFixed(2);
        top = top.toFixed(2);

        content.find('[name=left]').val(left).data('oldval', left);
        content.find('[name=bottom]').val(bottom).data('oldval', bottom);
        content.find('[name=right]').val(right).data('oldval', right);
        content.find('[name=top]').val(top).data('oldval', top);

        editor._source_image_repositioned();
    },
    _fixed_point_changed: function() {
        var content = $('#sidebar'),
            fixed_x = parseFloat(content.find('[name=fixed_x]').val()),
            fixed_y = parseFloat(content.find('[name=fixed_y]').val()),
            valid = (!isNaN(fixed_x) && !isNaN(fixed_y)),
            latlng = valid ? L.GeoJSON.coordsToLatLng([fixed_x, fixed_y]) : null;

        if (editor._fixed_point_layer) {
            if (valid) {
                editor._fixed_point_layer.setLatLng(latlng);
            } else {
                editor._fixed_point_layer.remove();
                editor._fixed_point_layer = null;
            }
        } else if (valid) {
            editor._fixed_point_layer = L.marker(latlng, {draggable: true, autoPan: true}).on('dragend', function(e) {
                var coords = L.GeoJSON.latLngToCoords(e.target.getLatLng());
                content.find('[name=fixed_x]').val(coords[0].toFixed(3));
                content.find('[name=fixed_y]').val(coords[1].toFixed(3));
            });
            editor._fixed_point_layer.addTo(editor.map);
        }
    },
    _copy_from_changed: function() {
        var content = $('#sidebar'),
            value = JSON.parse($(this).val());
        $(this).val('');
        if (!confirm('Are you sure you want to copy settings from '+value.name+'?')) return;
        delete value.name;
        for (var key in value) {
            if (value.hasOwnProperty(key)) content.find('[name='+key+']').val(value[key]);
        }
        editor._source_image_calculate_scale();
        editor._source_image_repositioned();
    },

    // geometries
    geometrystyles: {},
    _loading_geometry: false,
    _geometries_layer: null,
    _line_geometries: [],
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
    _active_graph_node_html: null,
    _graph_edges_from: {},
    _graph_edges_to: {},
    _arrow_colors: [],
    _last_vertex: null,
    _num_vertices: 0,
    _orig_vertex_pos: null,
    _max_bounds: null,
    _creating_type: null,
    _shift_pressed: false,
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
        editor.map.on('editable:drawing:start editable:drawing:end', function() {
            editor._last_vertex = null;
            editor._num_vertices = 0;
        });
        editor.map.on('editable:vertex:new', function(e) {
            if (editor._shift_pressed && editor._creating && editor._creating_type === 'polygon' && editor._num_vertices === 1) {
                var firstPoint = new L.Point(editor._last_vertex.latlng.lng, editor._last_vertex.latlng.lat),
                    secondPoint = new L.Point(e.vertex.latlng.lng, e.vertex.latlng.lat),
                    center = new L.Point((firstPoint.x+secondPoint.x)/2, (firstPoint.y+secondPoint.y)/2),
                    radius = firstPoint.distanceTo(secondPoint)/2,
                    options = e.layer.options,
                    points = Math.min(32, 8+Math.floor(radius*5)*2),
                    vertices = [];
                for (var i=0;i<points;i++) {
                    vertices.push([
                        center.x+Math.sin(Math.PI*2/points*i)*radius,
                        center.y+Math.cos(Math.PI*2/points*i)*radius
                    ])
                }
                var polygon = L.polygon(L.GeoJSON.coordsToLatLngs(vertices), options).addTo(editor.map);
                window.setTimeout(function() {
                    editor.map.editTools.stopDrawing();
                    polygon.enableEdit();
                    editor._done_creating({layer: polygon});
                }, 100);
            }
            editor._last_vertex = e.vertex;
            editor._num_vertices++;
        });
        editor.map.on('editable:vertex:dragstart', function (e) {
            editor._orig_vertex_pos = [e.vertex.latlng.lat, e.vertex.latlng.lng];
        });
        editor.map.on('editable:vertex:dragend', function () {
            editor._orig_vertex_pos = null;
        });
        editor.map.on('editable:vertex:drag', function (e) {
            if (e.originalEvent.ctrlKey && editor._orig_vertex_pos) {
                var dx = e.latlng.lng - editor._orig_vertex_pos[1],
                    dy = e.latlng.lat - editor._orig_vertex_pos[0],
                    angle = Math.atan2(dy, dx) * (180 / Math.PI),
                    distance = Math.hypot(dx, dy),
                    newangle = Math.round(angle/15)*15 / (180 / Math.PI);
                e.latlng.lat = editor._orig_vertex_pos[0] + Math.sin(newangle)*distance;
                e.latlng.lng = editor._orig_vertex_pos[1] + Math.cos(newangle)*distance;
            }
            e.vertex.setLatLng([Math.round(e.latlng.lat*100)/100, Math.round(e.latlng.lng*100)/100]);
        });
        editor.map.on('editable:drawing:click editable:drawing:move', function (e) {
            if (e.originalEvent.ctrlKey && editor._last_vertex) {
                var dx = e.latlng.lng - editor._last_vertex.latlng.lng,
                    dy = e.latlng.lat - editor._last_vertex.latlng.lat,
                    angle = Math.atan2(dy, dx) * (180 / Math.PI),
                    distance = Math.hypot(dx, dy),
                    newangle = Math.round(angle/15)*15 / (180 / Math.PI);
                e.latlng.lat = editor._last_vertex.latlng.lat + Math.sin(newangle)*distance;
                e.latlng.lng = editor._last_vertex.latlng.lng + Math.cos(newangle)*distance;
            }
            e.latlng.lat = Math.round(e.latlng.lat*100)/100;
            e.latlng.lng = Math.round(e.latlng.lng*100)/100;
        });
        editor.map.on('editable:drawing:click', function (e) {
            editor._shift_pressed = e.originalEvent.altKey;
        });
        editor.map.on('editable:vertex:ctrlclick editable:vertex:metakeyclick', function (e) {
            e.vertex.continue();
            editor._last_vertex = e.vertex;
        });

        editor.map.on('zoomend', editor._adjust_line_zoom);

        c3nav_api.get('editor/geometrystyles')
            .then(geometrystyles => {
                editor.geometrystyles = geometrystyles;
                c3nav_api.get('editor/bounds')
                    .then(bounds => {
                        bounds = L.GeoJSON.coordsToLatLngs(bounds.bounds);
                        editor._max_bounds = bounds;
                        editor._set_max_bounds();
                        editor.map.fitBounds(bounds, {padding: [30, 50]});
                        editor.init_sidebar();
                    })
            })

        editor.get_sources();
    },
    _set_max_bounds: function(bounds) {
        bounds = bounds ? L.latLngBounds(editor._max_bounds[0], editor._max_bounds[1]).extend(bounds) : editor._max_bounds;
        editor.map.setMaxBounds(bounds);
    },
    _last_geometry_url: null,
    _last_geometry_update_cache_key: null,
    _last_geometry_cache: {},
    load_geometries: function (geometry_url, highlight_type, editing_id) {
        // load geometries from url
        var same_url = (editor._last_geometry_url === geometry_url);
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
        editor._line_geometries = [];
        editor._graph_edges_from = {};
        editor._graph_edges_to = {};

        editor._set_max_bounds();

        if (same_url && editor._last_geometry_update_cache_key) {
            geometry_url += '?update_cache_key='+editor._last_geometry_update_cache_key;
        }
        c3nav_api.get(geometry_url)
            .then(result => {
                var geometries = [], feature, new_cache = {}, feature_type, feature_id;
                // geometries cache logic
                for (var i=0;i<result.length;i++) {
                    feature = result[i];
                    if (Array.isArray(feature)) {
                        if (feature[0] === 'update_cache_key') {
                            editor._last_geometry_update_cache_key = feature[1];
                            continue;
                        }
                        // load from cache
                        if (feature[0] in editor._last_geometry_cache) {
                            feature = editor._last_geometry_cache[feature[0]][feature[1]];
                        } else {
                            feature = null;
                        }
                        if (!feature) {
                            editor._last_geometry_update_cache_key = null;
                            editor.load_geometries(editor._last_geometry_url, editor._highlight_type, editor._editing_id);
                            return;
                        }
                    }
                    if (!feature.properties.changed) {
                        if (!new_cache[feature.properties.type]) {
                            new_cache[feature.properties.type] = {};
                        }
                        new_cache[feature.properties.type][feature.properties.id] = feature;
                    }
                    geometries.push(feature);
                }
                editor._last_geometry_cache = new_cache;

                editor.map.removeLayer(editor._highlight_layer);
                editor._highlight_layer.clearLayers();
                if (editor._geometries_layer !== null) {
                    editor.map.removeLayer(editor._geometries_layer);
                }
                var remove_feature = null;
                if (editor._editing_id !== null) {
                    for (i=0;i<geometries.length;i++) {
                        feature = geometries[i];
                        if (feature.properties.original_type !== null && feature.properties.original_type+'-'+String(feature.properties.original_id) === editor._editing_id) {
                            remove_feature = i;
                        } else if (feature.original_geometry !== null && feature.properties.type+'-'+String(feature.properties.id) === editor._editing_id) {
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
                if (editor._bounds_layer === null && editor._geometries_layer.getLayers().length) editor._bounds_layer = editor._geometries_layer;
                if (editor._next_zoom && editor._bounds_layer !== null) {
                    editor.map.flyToBounds((editor._bounds_layer.getBounds !== undefined) ? editor._bounds_layer.getBounds() : [editor._bounds_layer.getLatLng(), editor._bounds_layer.getLatLng()], {
                        maxZoom: Math.max(4, editor.map.getZoom()),
                        duration: 0.5,
                        padding: [20, 20]
                    });
                }
                editor._next_zoom = null;
                editor.map.doubleClickZoom.enable();

                editor._adjust_line_zoom();

                if (editor.map.options.renderer._container !== undefined) {
                    var defs = editor.map.options.renderer._container.querySelector('defs');
                    if (defs === null) {
                        editor.map.options.renderer._container.insertAdjacentHTML('afterbegin', '<defs></defs>');
                        defs = editor.map.options.renderer._container.querySelector('defs');
                    } else {
                        defs.innerHTML = '';
                    }
                    for(i=0;i<editor._arrow_colors.length;i++) {
                        var color = editor._arrow_colors[i];
                        defs = editor.map.options.renderer._container.querySelector('defs');
                        // noinspection HtmlUnknownAttribute
                        defs.insertAdjacentHTML('beforeend', '<marker id="graph-edge-arrow-'+String(i)+'" markerWidth="2" markerHeight="3" refX="3.5" refY="1.5" orient="auto"><path d="M0,0 L2,1.5 L0,3 L0,0" fill="'+color+'"></path></marker>');
                    }
                }

                editor._check_start_editing();
            })
    },
    reload_geometries: function () {
        if ($('body').is('.map-enabled') && editor._last_geometry_url !== null) {
            editor.load_geometries(editor._last_geometry_url);
        }
    },
    _weight_for_zoom: function() {
        return Math.pow(2, editor.map.getZoom())*0.1;
    },
    _adjust_line_zoom: function() {
        var weight = Math.pow(2, editor.map.getZoom())*0.1,
            factor = Math.pow(2, editor.map.getZoom());
        editor._arrow_colors = [];
        for(var i=0;i<editor._line_geometries.length;i++) {
            var layer = editor._line_geometries[i];
            if (layer.feature.properties.type === 'stair') {
                layer.setStyle({weight: weight/2});
            } else {
                layer.setStyle({weight: weight});
            }
            if (layer.feature.properties.type === 'graphedge') {
                var start_pos = 0.1,
                    end_pos = layer.length-0.1,
                    color_index = editor._arrow_colors.indexOf(layer._path.getAttribute('stroke')),
                    other = (editor._graph_edges_to[layer.feature.properties.from_node] !== undefined) ? editor._graph_edges_to[layer.feature.properties.from_node][layer.feature.properties.to_node] : undefined;
                if (color_index === -1) {
                    color_index = editor._arrow_colors.length;
                    editor._arrow_colors.push(layer._path.getAttribute('stroke'));
                }
                if (other !== undefined) {
                    start_pos = layer.length/2-0.01;
                }
                if (other === undefined || layer._path.getAttribute('stroke') !== other._path.getAttribute('stroke')) {
                    end_pos = layer.length-0.3;
                    layer._path.setAttribute('marker-end', 'url(#graph-edge-arrow-'+String(color_index)+')');
                }
                layer.setStyle({
                    dashArray: '0 '+String(start_pos*factor)+' '+String((end_pos-start_pos)*factor)+' '+String(layer.length*factor)
                });
            }
        }
    },
    _line_draw_geometry_style: function(style) {
        style.stroke = true;
        style.color = style.fillColor;
        style.weight = editor._weight_for_zoom();
        style.lineCap = 'butt';
        return style;
    },
    _point_to_layer: function (feature, latlng) {
        return L.circle(latlng, {radius: 0.15});
    },
    _get_geometry_style: function (feature) {
        // style callback for GeoJSON loader
        var style = editor._get_mapitem_type_style(feature.properties.type);
        if (editor._level_control.current_level_id === editor._sublevel_control.current_level_id) {
            if (editor._sublevel_control.level_ids.indexOf(feature.properties.level) >= 0 && editor._level_control.current_level_id !== feature.properties.level) {
                style.stroke = true;
                style.weight = 1;
                style.color = '#ffffff';
            }
        } else {
            if (feature.properties.level !== null && editor._sublevel_control.current_level_id !== feature.properties.level) {
                style.fillOpacity = 0.5;
            }
        }
        if (feature.properties.type === 'graphnode' && feature.properties.id === editor._active_graph_node) {
            style.stroke = true;
            style.weight = 3;
            style.color = '#00ff00';
        }
        if (feature.properties.color !== null) {
            style.fillColor = feature.properties.color;
        }
        if (feature.geometry.type === 'LineString') {
            style = editor._line_draw_geometry_style(style);
        }
        if (feature.properties.opacity !== null) {
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
        if (feature.geometry.type === 'LineString') {
            editor._line_geometries.push(layer);
            layer.length = Math.pow(Math.pow(layer._latlngs[0].lat-layer._latlngs[1].lat, 2)+Math.pow(layer._latlngs[0].lng-layer._latlngs[1].lng, 2), 0.5);
        }
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
        } else if (feature.properties.type === 'graphedge') {
            if (editor._graph_edges_from[feature.properties.from_node] === undefined) {
                editor._graph_edges_from[feature.properties.from_node] = {}
            }
            editor._graph_edges_from[feature.properties.from_node][feature.properties.to_node] = layer;
            if (editor._graph_edges_to[feature.properties.to_node] === undefined) {
                editor._graph_edges_to[feature.properties.to_node] = {}
            }
            editor._graph_edges_to[feature.properties.to_node][feature.properties.from_node] = layer;
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
        if (!geometry) return;
        if (Object.keys(geometry._bounds).length === 0) return; // ignore geometries with empty bounds
        geometry.setStyle({
            color: '#FFFFDD',
            weight: 3,
            opacity: 1,
            fillOpacity: 0
        });
        geometry.list_elem.addClass('highlight');
    },
    _unhighlight_geometry: function(id) {
        // unhighlight whatever is highlighted currently
        var geometry = editor._highlight_geometries[id];
        if (!geometry) return;
        if (Object.keys(geometry._bounds).length === 0) return; // ignore geometries with empty bounds
        geometry.setStyle({
            weight: 3,
            opacity: 0,
            fillOpacity: 0
        });
        geometry.list_elem.removeClass('highlight');
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
        if (editor._active_graph_node === e.target.feature.properties.id) {
            e.target.node_layer.setStyle({
                stroke: false
            });
            e.target.setStyle({
                opacity: 0
            });
            var sidebar = $('#sidebar');
            sidebar.find('[data-active-node]').remove();
            sidebar.find('#id_active_node').val('');
            editor._active_graph_node = null;
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
            var options, mapitem_type = form.attr('data-new');
            var geometry_value = geometry_field.val();
            if (geometry_value === 'null') geometry_value = '';
            if (geometry_value) {
                editor._creating_type = null;
                if (editor._editing_layer !== null) {
                    options = editor._editing_layer.options;
                    editor._editing_layer.remove();
                } else if (mapitem_type) {
                    // creating a new geometry, already drawn but form was rejected
                    options = editor._get_mapitem_type_style(mapitem_type);
                    if (mapitem_type === 'area') {
                        options.fillOpacity = 0.5;
                    }
                }
                if (options) {
                    editor._editing_layer = L.geoJSON(JSON.parse(geometry_field.val()), {
                        style: function() { return options; },
                        pointToLayer: editor._point_to_layer,
                    }).getLayers()[0].addTo(editor._geometries_layer);
                    editor._editing_layer.enableEdit();
                    if (editor._editing_layer.editor._resizeLatLng !== undefined) {
                        editor._editing_layer.editor._resizeLatLng.__vertex._icon.style.display = 'none';
                    }
                }
            } else if (form.is('[data-new]')) {
                // create new geometry
                options = editor._get_mapitem_type_style(mapitem_type);
                if (mapitem_type === 'area') {
                    options.fillOpacity = 0.5;
                }
                form.addClass('creation-lock');
                var geomtype = form.attr('data-geomtype');
                editor._creating_type = geomtype;
                if (geomtype === 'polygon') {
                    editor.map.editTools.startPolygon(null, options);
                } else if (geomtype === 'linestring') {
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
            //e.layer.remove();
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
                layer.setRadius(0.15);
                e.layer.remove();
            }
            editor._editing_layer = layer;
            editor._editing_layer.addTo(editor._geometries_layer);
            if (e.layer._latlng !== undefined) {
                layer.enableEdit();
                layer.editor._resizeLatLng.__vertex._icon.style.display = 'none';
            }
            editor._update_editing();
            $('#sidebar').find('.content').find('form.creation-lock').removeClass('creation-lock')
                .find('input:not([type=hidden], .btn)').first().focus();
        }
    },
    _update_editing: function () {
        // called if the temporary drawing layer changes. if we are in editing mode (not creating), update the form.
        if (editor._editing_layer !== null) {
            $('#id_geometry').val(JSON.stringify(editor._editing_layer.toGeoJSON().geometry));
        }
    },

    init_wificollector: function () {
        // init geometries and edit listeners
        editor._highlight_layer = L.layerGroup().addTo(editor.map);

        $('#sidebar').on('click', '.wificollector .start', editor._wificollector_start)
                     .on('click', '.wificollector .stop', editor._wificollector_stop)
                     .on('click', '.wificollector .reset', editor._wificollector_reset);
        window.setInterval(editor._wificollector_scan_perhaps, 1000);
    },
    _wificollector_data: [],
    _wificollector_start: function () {
        var $collector = $('#sidebar').find('.wificollector');
        $collector.removeClass('empty').addClass('running');
        editor._wificollector_data = [];
        $collector.find('.count').text(0);
        if (mobileclient.wificollectorStart) mobileclient.wificollectorStart();
    },
    _wificollector_stop: function () {
        if (mobileclient.wificollectorStop) mobileclient.wificollectorStop();
        if (!editor._wificollector_data.length) return editor._wificollector_reset();
        var $collector = $('#sidebar').find('.wificollector');
        $collector.removeClass('running').delay(1000).queue(function(n) {
            $(this).addClass('done');
            n();
        });
        $collector.closest('form').removeClass('scan-lock');
    },
    _wificollector_reset: function () {
        var $collector = $('#sidebar').find('.wificollector');
        $collector.removeClass('done').removeClass('running').addClass('empty').find('table').html('');
        $collector.siblings('[name=data]').val('');
        $collector.closest('form').addClass('scan-lock');
    },
    _wificollector_last_max_last: 0,
    _wificollector_last_result: 0,
    _wificollector_result: function(data) {
        var $collector = $('#sidebar').find('.wificollector.running'),
            $table = $collector.find('table'),
            item, i, line, apid, color, max_last = 0, now = Date.now();
        editor._scan_waits = false;

        if (!data.length) return;
        if (now-2000 < editor._wificollector_last_result) return;
        editor._wificollector_last_result = now;

        // ignore this scan?
        for (i=0; i < data.length; i++) {
            item = data[i];
            if (item.last) {
                max_last = Math.max(max_last, item.last);
            }
        }
        if (max_last && editor._wificollector_last_max_last && max_last === editor._max_last_max) return;
        editor._wificollector_last_max_last = max_last;

        $table.find('tr').addClass('old');
        for (i=0; i < data.length; i++) {
            item = data[i];
            // App version < 4.2.4 use level instead fo rssi
            if (item.level !== undefined) {
                item.rssi = item.level;
                delete item.level
            }
            apid = 'ap-'+item.bssid.replace(/:/g, '-');
            line = $table.find('tr.'+apid);
            color = Math.max(0, Math.min(50, item.rssi+80));
            color = 'rgb('+String(250-color*5)+', '+String(color*4)+', 0)';
            if (line.length) {
                line.removeClass('old').find(':last-child').text(item.rssi).css('color', color);
            } else {
                line = $('<tr>').addClass(apid);
                line.append($('<td>').text(item.bssid));
                line.append($('<td>').text(item.ssid));
                line.append($('<td>').text(item.rssi).css('color', color));
                $table.append(line);
            }
        }
        editor._wificollector_data.push(data);
        $collector.find('.count').text(editor._wificollector_data.length);
        $collector.siblings('[name=data]').val(JSON.stringify(editor._wificollector_data));
    },
    _scan_waits: false,
    _wificollector_scan_perhaps: function() {
        if (!editor._scan_waits && $('#sidebar').find('.wificollector.running').length) {
            editor._scan_waits = true;
            mobileclient.scanNow();
        }
    }
};

function nearby_stations_available() {
    editor._wificollector_result(JSON.parse(mobileclient.getNearbyStations()));
}


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
