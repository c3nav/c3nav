editor = {
    options: {
        position: 'bottomright'
    },

    init: function () {
        // Init Map
        editor.map = L.map('map', {
            renderer: L.svg({padding: 2}),
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

        $('#show_map').click(function (e) {
            e.preventDefault();
            $('body').addClass('show-map');
        });
        $('#show_details').click(function (e) {
            e.preventDefault();
            $('body').removeClass('show-map');
        });

        editor._level_control = new LevelControl().addTo(editor.map);
        editor._sublevel_control = new LevelControl({addClasses: 'leaflet-control-sublevels'}).addTo(editor.map);

        editor._level_control_container = $(editor._level_control._container);
        editor._sublevel_control_container = $(editor._sublevel_control._container);

        editor.init_geometries();
        editor.init_scancollector();
        editor.sidebar_content_loaded();
    },
    _inform_mobile_client: function (elem) {
        if (!window.mobileclient || !elem.length) return;
        var data = JSON.parse(elem.attr('data-user-data'));
        data.changes_count_display = elem.attr('data-count-display');
        data.direct_editing = elem.is('[data-direct-editing]');
        data.has_changeset = elem.is('[data-has-changeset]');
        mobileclient.setUserData(JSON.stringify(data));
    },
    _onbeforeunload: function (e) {
        if ($('#sidebar').find('[data-onbeforeunload]').length) {
            e.returnValue = true;
        }
    },

    // sources
    get_sources: function () {
        // load sources
        c3nav_api.get('mapdata/sources')
            .then(sources => Object.groupBy(sources, s => s.group ?? 'Ungrouped'))
            .then(async sourceGroups => {
                const control = new OverlayControl();
                for (const key in sourceGroups) {
                    const sources = sourceGroups[key];
                    for (var i = 0; i < sources.length; i++) {
                        const source = sources[i];
                        const bounds = L.GeoJSON.coordsToLatLngs(source.bounds);
                        options = {opacity: 0.3};
                        source.layer = L.imageOverlay('/editor/sourceimage/' + source.name, bounds, options);
                        const is_svg = source.name.endsWith('.svg');
                        control.addOverlay(source.layer, is_svg ? `${source.name} (image overlay)` : source.name, key);

                        if (is_svg) {
                            source.svg_el = document.createElementNS("http://www.w3.org/2000/svg", "svg");
                            source.svg_el.setAttribute('xmlns', "http://www.w3.org/2000/svg");
                            source.svg_layer = L.svgOverlay(source.svg_el, bounds, options);
                            control.addOverlay(source.svg_layer, `${source.name} (svg overlay)`, key);
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
                }
                control.addTo(editor.map);
            });
    },

    // sidebar
    _last_non_modal_path: null,
    _last_graph_path: null,
    get_location_path: function () {
        return window.location.pathname + window.location.search;
    },
    init_sidebar: function () {
        // init the sidebar. sed listeners for form submits and link clicks
        $('#sidebar').find('.content').on('click', 'a[href]', editor._sidebar_link_click)
            .on('click', 'button[type=submit]', editor._sidebar_submit_btn_click)
            .on('submit', 'form', editor._sidebar_submit);
        $('nav.navbar').on('click', 'a[href]', editor._sidebar_link_click);
        var location_path = editor.get_location_path();
        editor._sidebar_loaded();
        history.replaceState({}, '', location_path);
        window.onpopstate = function () {
            editor.sidebar_get(editor.get_location_path(), true);
        };
    },
    sidebar_get: function (location, no_push) {
        // load a new page into the sidebar using a GET request
        if (!no_push) history.pushState({}, '', location);
        editor._sidebar_unload();
        $.get(location, editor._sidebar_loaded).fail(editor._sidebar_error);
    },
    _sidebar_unload: function () {
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

        if (window.mobileclient && mobileclient.wificollectorStop && $('#sidebar').find('.scancollector.running').length) {
            mobileclient.wificollectorStop();
        }

        $('#sidebar').addClass('loading').find('.content').html('');
        editor._cancel_editing();
        editor._destroy_staircase_editing();
    },
    _fill_level_control: function (level_control, level_list, geometryURLs) {
        var levels = level_list.find('a');
        level_control.geometryURLs = !!geometryURLs;
        if (levels.length) {
            for (var i = 0; i < levels.length; i++) {
                var level = $(levels[i]);
                level_control.addLevel(level.attr('data-id'), level.text(), level.attr('href'), geometryURLs ? (i==0) : level.is('.current'));
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

    sidebar_content_loaded: function () {
        if (document.querySelector('#sidebar [data-themed-color]')) {
            editor.theme_editor_loaded();
        }
        if (document.querySelector('TODO')) {

        }
    },
    theme_editor_loaded: function () {
        const filter_show_all = () => {
            for (const input of document.querySelectorAll('#sidebar [data-themed-color]')) {
                input.parentElement.classList.remove('theme-color-hidden');
            }
        };
        const filter_show_base = () => {
            for (const input of document.querySelectorAll('#sidebar [data-themed-color]')) {
                input.parentElement.classList.toggle('theme-color-hidden',
                    !('colorBaseTheme' in input.dataset));
            }
        };
        const filter_show_any = () => {
            for (const input of document.querySelectorAll('#sidebar [data-themed-color]')) {
                input.parentElement.classList.toggle('theme-color-hidden',
                    !('colorBaseTheme' in input.dataset || 'colorsOtherThemes' in input.dataset));
            }
        };

        const filterButtons = document.querySelector('body>.theme-editor-filter').cloneNode(true);
        const first_color_input = document.querySelector('#sidebar [data-themed-color]:first-of-type');
        first_color_input.parentElement.before(filterButtons);
        filterButtons.addEventListener('click', e => {
            const btn = e.target;
            if (btn.classList.contains('active')) return;
            for (const b of filterButtons.querySelectorAll('button')) {
                b.classList.remove('active');
            }
            btn.classList.add('active');
            if ('all' in btn.dataset) filter_show_all();
            else if ('baseTheme' in btn.dataset) filter_show_base();
            else if ('anyTheme' in btn.dataset) filter_show_any();
        });

        const baseInfoElement = document.querySelector('body>.theme-color-info');

        for (const color_input of document.querySelectorAll('#sidebar [data-themed-color]')) {
            let colors = {};
            if ('colorBaseTheme' in color_input.dataset) {
                colors.base = color_input.dataset.colorBaseTheme;
            }
            if ('colorsOtherThemes' in color_input.dataset) {
                const other_themes = JSON.parse(color_input.dataset.colorsOtherThemes);
                colors = {...colors, ...other_themes};
            }
            const titleStr = Object.entries(colors).map(([theme, color]) => `${theme}: ${color}`).join('&#10;');
            if (!titleStr) continue;
            const infoElement = baseInfoElement.cloneNode(true);
            infoElement.title = titleStr;
            const label = color_input.previousElementSibling;
            label.classList.add('theme-color-label');
            label.appendChild(infoElement);
        }
    },

    _convert_pasted_to_lowercase: function (e) {
        window.setTimeout(() => {
            e.target.value = e.target.value.toLowerCase();
        }, 100);
    },

    _in_modal: false,
    sidebar_extra_data: {},
    _sidebar_loaded: function (data) {
        // sidebar was loaded. load the content. check if there are any redirects. call _check_start_editing.
        var content = $('#sidebar').removeClass('loading').find('.content');
        if (data !== undefined) {
            var doc = (new DOMParser).parseFromString(data, 'text/html');
            content[0].replaceChildren(...doc.body.children);
            editor.sidebar_content_loaded();
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

        editor._beacon_layer.clearLayers();

        const extraData = content.find('#sidebar-extra-data').first().text();

        if (extraData) {
            editor.sidebar_extra_data = JSON.parse(extraData);
        } else {
            editor.sidebar_extra_data = null;
        }

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
            content.find('[name=left], [name=bottom], [name=right], [name=top]').each(function () {
                $(this).data('oldval', $(this).val());
            });

            content.find('[name=lock_aspect], [name=lock_scale]').closest('.form-group').addClass('source-wizard');

            var source_width = (parseFloat(content.find('[name=right]').val()) || 0) - (parseFloat(content.find('[name=left]').val()) || 0),
                source_height = (parseFloat(content.find('[name=top]').val()) || 0) - (parseFloat(content.find('[name=bottom]').val()) || 0);
            editor._source_aspect_ratio = source_width / (source_height || 1);
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
        var level_geometry_urls = content.find('[data-level-geometry-urls]');
        var $body = $('body');
        if (geometry_url.length) {
            geometry_url = geometry_url.attr('data-geometry-url');
        } else if (level_geometry_urls.length) {
            geometry_url = content.find('[data-levels]').find('a').first().attr('href');
        } else {
            geometry_url = null;
        }
        if (geometry_url) {
            var highlight_type = content.find('[data-list]');
            var editing_id = content.find('[data-editing]');
            var access_restriction_select = content.find('[data-access-restriction-select]');
            if (editor._next_zoom === null) {
                editor._next_zoom = !content.find('[data-nozoom]').length;
            }
            editor.accessRestrictionSelect = access_restriction_select.length ? $(content.find("[name=members]")[0]) : null;
            editor.load_geometries(
                geometry_url,
                (highlight_type.length ? highlight_type.attr('data-list') : null),
                (editing_id.length ? editing_id.attr('data-editing') : null)
            );
            $body.addClass('map-enabled');
            editor._level_control.clearLevels();
            editor._sublevel_control.clearLevels();

            editor._fill_level_control(editor._level_control, content.find('[data-levels]'), level_geometry_urls.length);
            editor._fill_level_control(editor._sublevel_control, content.find('[data-sublevels]'));

            var level_control_offset = $(editor._level_control_container).position();
            var offset_parent = $(editor._level_control_container).offsetParent();
            $(editor._sublevel_control._container).css({
                bottom: offset_parent.outerHeight() - level_control_offset.top - editor._level_control_container.outerHeight() - parseInt(editor._level_control_container.css('margin-bottom')),
                right: offset_parent.outerWidth() - level_control_offset.left
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
            var collector = $($('body .scancollector')[0].outerHTML);
            editor.load_scancollector_lookup();

            var existing_data = [];
            if (data_field.val()) {
                existing_data = JSON.parse(data_field.val());
            }
            if (existing_data?.wifi?.length || existing_data?.ibeacon?.length > 0) {
                collector.removeClass('empty').addClass('done');
                collector.find('.wifi-count').text(existing_data?.wifi?.length);
                collector.find('.ibeacon-count').text(existing_data?.ibeacon?.length);
            } else {
                if (window.mobileclient) {
                    $('[for=id_fill_quest]').hide();
                    data_field.closest('form').addClass('scan-lock');
                }
            }
            data_field.after(collector);
        }

        content.find('#id_slug').on('paste', editor._convert_pasted_to_lowercase);
        content.find('#id_redirect_slugs').on('paste', editor._convert_pasted_to_lowercase);
    },
    _sidebar_error: function (data) {
        $('#sidebar').removeClass('loading').find('.content').html('<h3>Error ' + data.status + '</h3>' + data.statusText);
        editor._level_control.hide();
        editor._sublevel_control.hide();
    },
    _sidebar_link_click: function (e) {
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
    _sidebar_submit_btn_click: function () {
        // listener for submit-button-clicks in the sidebar, so the submit event will know which button submitted.
        if (editor._loading_geometry) return;
        $(this).closest('form').data('btn', $(this)).clearQueue().delay(300).queue(function () {
            $(this).data('btn', null);
        });
    },
    _sidebar_submit: function (e) {
        // listener for form submits in the sidebar.
        e.preventDefault();
        if (editor._loading_geometry || $(this).is('.creation-lock') || $(this).is('.scan-lock')) return;
        if (editor._staircase_layer) {
            editor._staircase_submit($(this));
            return;
        }
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
    _source_name_selected: function () {
        if (editor._source_image_layer) {
            editor._source_image_layer.remove();
            editor._source_image_layer = null;
        }
        // noinspection HtmlRequiredAltAttribute
        $('<img src="/editor/sourceimage/' + $(this).val() + '">').on('load', editor._source_name_selected_ajax_callback);
        $('#sidebar form').removeClass('show-source-wizard');
        $('body').removeClass('map-enabled');
    },
    _source_name_selected_ajax_callback: function () {
        if ($(this).attr('src').endsWith($('#sidebar [name=name]').val())) {
            $('#sidebar form').addClass('show-source-wizard');
            $(this).appendTo('body').hide();
            editor._source_image_orig_width = $(this).width();
            editor._source_image_orig_height = $(this).height();
            $(this).remove();
            $('body').addClass('map-enabled');
            var content = $('#sidebar');
            if (content.find('[data-new]').length || isNaN(parseFloat(content.find('[name=right]').val())) || isNaN(parseFloat(content.find('[name=left]').val())) || isNaN(parseFloat(content.find('[name=top]').val())) || isNaN(parseFloat(content.find('[name=bottom]').val()))) {
                editor._source_aspect_ratio = $(this).width() / $(this).height();
                content.find('[name=left]').val(0).data('oldval', 0);
                content.find('[name=bottom]').val(0).data('oldval', 0);
                var factor = 1;
                while (factor < 1000 && (editor._source_image_orig_width / factor) > 1500) {
                    factor *= 10;
                }
                var width = (editor._source_image_orig_width / factor).toFixed(2),
                    height = (editor._source_image_orig_height / factor).toFixed(2);
                content.find('[name=right]').val(width).data('oldval', width);
                content.find('[name=top]').val(height).data('oldval', height);
                content.find('[name=scale_x]').val(1 / factor);
                content.find('[name=scale_y]').val(1 / factor);
            } else {
                editor._source_image_calculate_scale();
            }
            editor._source_image_repositioned();
        }
    },
    _source_image_repositioned: function () {
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
            editor._source_image_layer = L.imageOverlay('/editor/sourceimage/' + content.find('[name=name]').val(), bounds, {
                opacity: 0.3,
                zIndex: 10000
            });
            editor._source_image_layer.addTo(editor.map);
            if (content.find('[data-new]').length) {
                editor.map.fitBounds(bounds, {padding: [30, 50]});
            }
        }
    },
    _source_image_calculate_scale: function () {
        var content = $('#sidebar');
        var source_width = parseFloat(content.find('[name=right]').val()) - parseFloat(content.find('[name=left]').val()),
            source_height = parseFloat(content.find('[name=top]').val()) - parseFloat(content.find('[name=bottom]').val());
        if (isNaN(source_width) || isNaN(source_height)) return;
        var scale_x = (source_width / editor._source_image_orig_width).toFixed(3),
            scale_y = (source_height / editor._source_image_orig_height).toFixed(3);
        content.find('[name=scale_x]').val(scale_x);
        content.find('[name=scale_y]').val(scale_y);
        if (scale_x !== scale_y) {
            content.find('[name=lock_aspect]').prop('checked', false);
        }
    },
    _source_image_bounds_changed: function () {
        var content = $('#sidebar'),
            lock_scale = content.find('[name=lock_scale]').prop('checked'),
            oldval = $(this).data('oldval'),
            newval = $(this).val(),
            diff = parseFloat(newval) - parseFloat(oldval);
        $(this).data('oldval', newval);
        if (lock_scale) {
            if (!isNaN(diff)) {
                var other_field_name = {
                        left: 'right',
                        right: 'left',
                        top: 'bottom',
                        bottom: 'top'
                    }[$(this).attr('name')],
                    other_field = content.find('[name=' + other_field_name + ']'),
                    other_val = parseFloat(other_field.val());
                if (!isNaN(other_val)) {
                    other_field.val((other_val + diff).toFixed(2)).data('oldval', other_val);
                }
            }
        } else {
            editor._source_image_calculate_scale();
        }
        editor._source_image_repositioned();
    },
    _source_image_scale_changed: function () {
        var content = $('#sidebar'),
            lock_aspect = content.find('[name=lock_scale]').prop('checked');
        if (lock_aspect) {
            var other_field_name = {scale_x: 'scale_y', scale_y: 'scale_x'}[$(this).attr('name')],
                other_field = content.find('[name=' + other_field_name + ']');
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

        var fixed_x_relative = (fixed_x - left) / (right - left),
            fixed_y_relative = (fixed_y - bottom) / (top - bottom),
            width = editor._source_image_orig_width * scale_x,
            height = editor._source_image_orig_height * scale_y;
        left = fixed_x - (width * fixed_x_relative);
        bottom = fixed_y - (height * fixed_y_relative);
        right = left + width;
        top = bottom + height;

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
    _fixed_point_changed: function () {
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
            editor._fixed_point_layer = L.marker(latlng, {draggable: true, autoPan: true}).on('dragend', function (e) {
                var coords = L.GeoJSON.latLngToCoords(e.target.getLatLng());
                content.find('[name=fixed_x]').val(coords[0].toFixed(3));
                content.find('[name=fixed_y]').val(coords[1].toFixed(3));
            });
            editor._fixed_point_layer.addTo(editor.map);
        }
    },
    _copy_from_changed: function () {
        var content = $('#sidebar'),
            value = JSON.parse($(this).val());
        $(this).val('');
        if (!confirm('Are you sure you want to copy settings from ' + value.name + '?')) return;
        delete value.name;
        for (var key in value) {
            if (value.hasOwnProperty(key)) content.find('[name=' + key + ']').val(value[key]);
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
    _beacon_layer: null,
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
            .on('mouseenter', '[name=members] option', editor._hover_members_option)
            .on('mouseleave', '[name=members] option', editor._unhover_members_option)
            .on('click', '.itemtable tr[data-pk] td:not(:last-child)', editor._click_mapitem_row);

        editor.map.on('editable:drawing:commit', editor._done_creating);
        editor.map.on('editable:editing', editor._update_editing);
        editor.map.on('editable:drawing:cancel', editor._canceled_creating);
        editor.map.on('editable:vertex:click', function () {
            editor.map.doubleClickZoom.disable();
        });
        editor.map.on('editable:drawing:start editable:drawing:end', function () {
            editor._last_vertex = null;
            editor._num_vertices = 0;
        });
        editor.map.on('editable:vertex:new', function (e) {
            if (editor._shift_pressed && editor._creating && editor._creating_type === 'polygon' && editor._num_vertices === 1) {
                var firstPoint = new L.Point(editor._last_vertex.latlng.lng, editor._last_vertex.latlng.lat),
                    secondPoint = new L.Point(e.vertex.latlng.lng, e.vertex.latlng.lat),
                    center = new L.Point((firstPoint.x + secondPoint.x) / 2, (firstPoint.y + secondPoint.y) / 2),
                    radius = firstPoint.distanceTo(secondPoint) / 2,
                    options = e.layer.options,
                    points = Math.min(32, 8 + Math.floor(radius * 5) * 2),
                    vertices = [];
                for (var i = 0; i < points; i++) {
                    vertices.push([
                        center.x + Math.sin(Math.PI * 2 / points * i) * radius,
                        center.y + Math.cos(Math.PI * 2 / points * i) * radius
                    ])
                }
                var polygon = L.polygon(L.GeoJSON.coordsToLatLngs(vertices), options).addTo(editor.map);
                window.setTimeout(function () {
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
                    newangle = Math.round(angle / 15) * 15 / (180 / Math.PI);
                e.latlng.lat = editor._orig_vertex_pos[0] + Math.sin(newangle) * distance;
                e.latlng.lng = editor._orig_vertex_pos[1] + Math.cos(newangle) * distance;
            }
            e.vertex.setLatLng([Math.round(e.latlng.lat * 100) / 100, Math.round(e.latlng.lng * 100) / 100]);
        });
        editor.map.on('editable:drawing:click editable:drawing:move', function (e) {
            if (e.originalEvent.ctrlKey && editor._last_vertex) {
                var dx = e.latlng.lng - editor._last_vertex.latlng.lng,
                    dy = e.latlng.lat - editor._last_vertex.latlng.lat,
                    angle = Math.atan2(dy, dx) * (180 / Math.PI),
                    distance = Math.hypot(dx, dy),
                    newangle = Math.round(angle / 15) * 15 / (180 / Math.PI);
                e.latlng.lat = editor._last_vertex.latlng.lat + Math.sin(newangle) * distance;
                e.latlng.lng = editor._last_vertex.latlng.lng + Math.cos(newangle) * distance;
            }
            e.latlng.lat = Math.round(e.latlng.lat * 100) / 100;
            e.latlng.lng = Math.round(e.latlng.lng * 100) / 100;
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

        editor._beacon_layer = L.layerGroup().addTo(editor.map);
    },
    _set_max_bounds: function (bounds) {
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
            geometry_url += '?update_cache_key=' + editor._last_geometry_update_cache_key;
        }
        c3nav_api.get(geometry_url)
            .then(result => {
                var geometries = [], feature, new_cache = {}, feature_type, feature_id;
                // geometries cache logic
                for (var i = 0; i < result.length; i++) {
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
                    for (i = 0; i < geometries.length; i++) {
                        feature = geometries[i];
                        if (feature.properties.original_type !== null && feature.properties.original_type + '-' + String(feature.properties.original_id) === editor._editing_id) {
                            remove_feature = i;
                        } else if (feature.original_geometry !== null && feature.properties.type + '-' + String(feature.properties.id) === editor._editing_id) {
                            feature.geometry = feature.original_geometry;
                            break;
                        }
                    }
                }
                if (remove_feature !== null) {
                    geometries.splice(remove_feature, 1);
                }
                if (editor._last_graph_path === null) {
                    geometries = geometries.filter(function (val) {
                        return val.properties.type !== 'graphnode' && val.properties.type !== 'graphedge'
                    })
                }

                if (editor.sidebar_extra_data?.activeOverlayId) {
                    geometries = geometries.filter(g => g.properties.type !== 'dataoverlayfeature' || g.properties.overlay === editor.sidebar_extra_data.activeOverlayId);
                } else {
                    geometries = geometries.filter(g => g.properties.type !== 'dataoverlayfeature');
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
                    for (i = 0; i < editor._arrow_colors.length; i++) {
                        var color = editor._arrow_colors[i];
                        defs = editor.map.options.renderer._container.querySelector('defs');
                        // noinspection HtmlUnknownAttribute
                        defs.insertAdjacentHTML('beforeend', '<marker id="graph-edge-arrow-' + String(i) + '" markerWidth="2" markerHeight="3" refX="3.5" refY="1.5" orient="auto"><path d="M0,0 L2,1.5 L0,3 L0,0" fill="' + color + '"></path></marker>');
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
    _weight_for_zoom: function () {
        return Math.pow(2, editor.map.getZoom()) * 0.1;
    },
    _adjust_line_zoom: function () {
        var weight = Math.pow(2, editor.map.getZoom()) * 0.1,
            factor = Math.pow(2, editor.map.getZoom());
        editor._arrow_colors = [];
        for (var i = 0; i < editor._line_geometries.length; i++) {
            var layer = editor._line_geometries[i];
            if (layer.feature.properties.type === 'stair') {
                layer.setStyle({weight: weight / 2});
            } else {
                layer.setStyle({weight: weight});
            }
            if (layer.feature.properties.type === 'graphedge') {
                var start_pos = 0.1,
                    end_pos = layer.length - 0.1,
                    color_index = editor._arrow_colors.indexOf(layer._path.getAttribute('stroke')),
                    other = (editor._graph_edges_to[layer.feature.properties.from_node] !== undefined) ? editor._graph_edges_to[layer.feature.properties.from_node][layer.feature.properties.to_node] : undefined;
                if (color_index === -1) {
                    color_index = editor._arrow_colors.length;
                    editor._arrow_colors.push(layer._path.getAttribute('stroke'));
                }
                if (other !== undefined) {
                    start_pos = layer.length / 2 - 0.01;
                }
                if (other === undefined || layer._path.getAttribute('stroke') !== other._path.getAttribute('stroke')) {
                    end_pos = layer.length - 0.3;
                    layer._path.setAttribute('marker-end', 'url(#graph-edge-arrow-' + String(color_index) + ')');
                }
                layer.setStyle({
                    dashArray: '0 ' + String(start_pos * factor) + ' ' + String((end_pos - start_pos) * factor) + ' ' + String(layer.length * factor)
                });
            }
        }
    },
    _line_draw_geometry_style: function (style) {
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
        if (editor._level_control.current_level_id === editor._sublevel_control.current_level_id || editor._sublevel_control.level_ids.length === 0) {
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

        if (feature.properties.type === 'dataoverlayfeature') {
            style.stroke = true;
            style.weight = 3;
            style.fillOpacity = 0.5;
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
            layer.length = Math.pow(Math.pow(layer._latlngs[0].lat - layer._latlngs[1].lat, 2) + Math.pow(layer._latlngs[0].lng - layer._latlngs[1].lng, 2), 0.5);
        }
        var highlight_access_restrictions = (editor._highlight_type == "accessrestriction" || editor.accessRestrictionSelect);
        if (feature.properties.type === editor._highlight_type || (highlight_access_restrictions && feature.properties.access_restriction)) {
            var highlight_id;
            if (highlight_access_restrictions) {
                highlight_id = feature.properties.access_restriction;
            } else {
                highlight_id = feature.properties.id;
            }
            var list_elem;
            if (editor.accessRestrictionSelect) {
                list_elem = editor.accessRestrictionSelect.find('option[value=' + String(highlight_id) + ']');
            } else {
                list_elem = $('#sidebar').find('[data-list] tr[data-pk=' + String(highlight_id) + ']');
            }
            if (list_elem.length === 0) return;
            var hasOption, optionSelected;
            if (editor.accessRestrictionSelect) {
                var option = editor.accessRestrictionSelect.find('[value=' + String(feature.properties.access_restriction) + ']');
                hasOption = !!option.length;
                optionSelected = option.is(':selected');
            } else {
                hasOption = false;
                optionSelected = false;
            }
            var highlight_layer = L.geoJSON(layer.feature, {
                style: function () {
                    return {
                        color: hasOption ? '#FF0000' : '#FFFFDD',
                        weight: (hasOption && !optionSelected) ? 1 : 3,
                        opacity: hasOption ? (optionSelected ? 1 : 0.3) : 0,
                        fillOpacity: 0,
                        className: 'c3nav-highlight'
                    };
                },
                pointToLayer: editor._point_to_layer
            }).getLayers()[0].addTo(editor._highlight_layer);
            highlight_layer.highlightID = highlight_id;
            highlight_layer.list_elem = list_elem;
            if (!editor._highlight_geometries[highlight_id]) editor._highlight_geometries[highlight_id] = [];
            editor._highlight_geometries[highlight_id].push(highlight_layer);
            highlight_layer.on('mouseover', editor._hover_geometry_layer)
                .on('mouseout', editor._unhover_geometry_layer)
                .on('click', editor._click_geometry_layer)
                .on('dblclick', editor._dblclick_geometry_layer);
        } else if (feature.properties.type + '-' + String(feature.properties.id) === editor._editing_id) {
            editor._editing_layer = layer;
            editor._bounds_layer = layer;
        } else if (feature.properties.bounds === true) {
            editor._bounds_layer = layer;
            if (editor._graph_creating) {
                var space_layer = L.geoJSON(layer.feature, {
                    style: function () {
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
                style: function () {
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
                style: function () {
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
    _hover_members_option: function () {
        // hover callback for a itemtable row
        if (editor._loading_geometry) return;
        if (!editor.accessRestrictionSelect) return;
        editor._highlight_geometry(parseInt($(this).val()));
    },
    _unhover_members_option: function () {
        // unhover callback for a itemtable row
        if (editor._loading_geometry) return;
        if (!editor.accessRestrictionSelect) return;
        editor._unhighlight_geometry(parseInt($(this).val()));
    },
    _click_mapitem_row: function () {
        if (editor._loading_geometry) return;
        geometries = editor._highlight_geometries[parseInt($(this).parent().attr('data-pk'))];
        if (geometries !== undefined) {
            var bounds = geometries[0].getBounds();
            for (let gemmetry of geometries.slice(1)) {
                bounds = bounds.extend(geometry.getBounds());
            }
            editor.map.flyToBounds(bounds, {  // todo fly to combined bounds
                maxZoom: 4,
                duration: 0.5,
                padding: [20, 20]
            });
        }
    },
    _hover_geometry_layer: function (e) {
        // hover callback for a geometry layer
        if (editor._loading_geometry) return;
        editor._highlight_geometry(
            (editor._highlight_type === "accessrestriction" || editor.accessRestrictionSelect)
            ? e.target.feature.properties.access_restriction
            : e.target.feature.properties.id
        );
    },
    _unhover_geometry_layer: function (e) {
        // unhover callback for a geometry layer
        if (editor._loading_geometry) return;
        editor._unhighlight_geometry(
            (editor._highlight_type === "accessrestriction" || editor.accessRestrictionSelect)
            ? e.target.feature.properties.access_restriction
            : e.target.feature.properties.id
        );
    },
    _click_geometry_layer: function (e) {
        // click callback for a geometry layer – scroll the corresponding itemtable row into view if it exists
        if (editor._loading_geometry) return;
        e.target.list_elem[0].scrollIntoView();
    },
    _dblclick_geometry_layer: function (e) {
        // dblclick callback for a geometry layer - edit this feature if the corresponding itemtable row exists
        if (editor._loading_geometry) return;
        if (editor.accessRestrictionSelect) {
            e.target.list_elem.prop('selected', !e.target.list_elem.prop('selected'));
        } else {
            e.target.list_elem.find('td:last-child a').click();
            e.target.list_elem.find('td:last-child a').click();
        }
        editor.map.doubleClickZoom.disable();
    },
    _highlight_geometry: function (id) {
        // highlight a geometries layer and itemtable row if they both exist
        var geometries = editor._highlight_geometries[id];
        if (!geometries) return;
        for (geometry of geometries) {
            geometry.setStyle({
                color: '#FFFFDD',
                weight: 3,
                opacity: 1,
                fillOpacity: 0
            });
            geometry.list_elem.addClass('highlight');
        }
    },
    _unhighlight_geometry: function (id) {
        // unhighlight whatever is highlighted currently
        var geometries = editor._highlight_geometries[id];
        if (!geometries) return;
        var option;
        for (geometry of geometries) {
            var hasOption, optionSelected;
            if (editor.accessRestrictionSelect) {
                option = editor.accessRestrictionSelect.find('[value=' + String(geometry.highlightID) + ']');
                hasOption = !!option.length;
                optionSelected = option.is(':selected');
            } else {
                hasOption = false;
                optionSelected = false;
            }
            geometry.setStyle({
                color: hasOption ? '#FF0000' : '#FFFFDD',
                weight: (hasOption && !optionSelected) ? 1 : 3,
                opacity: hasOption ? (optionSelected ? 1 : 0.3) : 0,
                fillOpacity: 0,
            });
            geometry.list_elem.removeClass('highlight');
        }
    },

    // graph events
    _hover_graph_item: function (e) {
        // hover callback for a graph node
        if (editor._loading_geometry) return;
        e.target.setStyle({
            color: '#FFFFDD',
            weight: 3,
            opacity: 1,
            fillOpacity: 0
        });
    },
    _unhover_graph_item: function (e) {
        // unhover callback for a graph node
        if (editor._loading_geometry) return;
        e.target.setStyle({
            weight: 3,
            opacity: 0,
            fillOpacity: 0
        });
    },
    _click_graph_current_space: function (e) {
        // click callback for a current graph space
        if (editor._loading_geometry) return;
        $('#id_clicked_position').val(JSON.stringify(L.marker(e.latlng).toGeoJSON().geometry)).closest('form').submit();
        editor.map.doubleClickZoom.disable();
    },
    _click_graph_node: function (e) {
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
    _dblclick_graph_other_space: function (e) {
        // click callback for an other graph space
        if (editor._loading_geometry) return;
        editor._next_zoom = true;
        $('#id_goto_space').val(e.target.feature.properties.id).closest('form').submit();
        editor.map.doubleClickZoom.disable();
    },

    _current_editing_shape: null,
    // edit and create geometries
    _check_start_editing: function () {
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
                    if (mapitem_type === 'area' || mapitem_type === 'staircase') {
                        options.fillOpacity = 0.5;
                    }
                }
                if (options) {
                    editor._editing_layer = L.geoJSON(JSON.parse(geometry_field.val()), {
                        style: function () {
                            return options;
                        },
                        pointToLayer: editor._point_to_layer,
                        multipoint: true,
                    }).getLayers()[0].addTo(editor._geometries_layer);
                    editor._editing_layer.enableEdit();
                    if (editor._editing_layer.editor._resizeLatLng !== undefined) {
                        editor._editing_layer.editor._resizeLatLng.__vertex._icon.style.display = 'none';
                    }
                }
            } else if (form.is('[data-new]')) {
                // create new geometry
                options = editor._get_mapitem_type_style(mapitem_type);
                if (mapitem_type === 'area' || mapitem_type === 'staircase') {
                    options.fillOpacity = 0.5;
                }
                form.addClass('creation-lock');
                const geomtypes = form.attr('data-geomtype').split(',');
                const default_geomtype = form.attr('data-default-geomtype');

                const startGeomEditing = (geomtype) => {
                    editor._creating_type = geomtype;
                    editor._creating = true;
                    if (editor._current_editing_shape) {
                        editor._current_editing_shape.remove();
                    }
                    if (geomtype === 'polygon') {
                        editor._current_editing_shape = editor.map.editTools.startPolygon(null, options);
                    } else if (geomtype === 'linestring') {
                        options = editor._line_draw_geometry_style(options);
                        editor._current_editing_shape = editor.map.editTools.startPolyline(null, options);
                    } else if (geomtype === 'point') {
                        editor._current_editing_shape = editor.map.editTools.startCircleMarker(null, options);
                    } else if (geomtype === 'multipoint') {
                        editor._current_editing_shape = editor.map.editTools.startMultipoint(null, options);
                    }
                }

                let selected_geomtype = geomtypes[0];

                if (geomtypes.length > 1) {
                    const selector = $('<select id="geomtype-selector"></select>');
                    const geomtypeNames = {
                        polygon: 'Polygon',
                        linestring: 'Line string',
                        multipoint: 'Multipoint',
                        point: 'Point',
                    }; // TODO: translations
                    for(const geomtype of geomtypes) {
                        const option = $(`<option value="${geomtype}">${geomtypeNames[geomtype]}</option>`);
                        if (geomtype === default_geomtype) {
                            option.attr('selected', true);
                            selected_geomtype = geomtype;
                        }
                        selector.append(option);
                    }

                    selector.on('change', e => startGeomEditing(e.target.value));
                    form.prepend(selector);
                }
                startGeomEditing(selected_geomtype);
            }

            if (mapitem_type === 'staircase') {
                editor._setup_staircase_editing();
            }
        }
    },
    _cancel_editing: function () {
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
    _done_creating: function (e) {
        // called when creating is completed (by clicking on the last point). fills in the form and switches to editing.
        if (editor._creating) {
            if (editor._creating_type !== 'multipoint') {
                // multipoints can always accept more points so they are always in "creating" mode
                editor._creating = false;
            }
            var layer = e.layer;
            if (editor._creating_type === 'point' && layer._latlng !== undefined) {
                layer = L.circle(layer._latlng, layer.options);
                layer.setRadius(0.15);
                e.layer.remove();
                editor._current_editing_shape = layer;
            }
            editor._editing_layer = layer;
            editor._editing_layer.addTo(editor._geometries_layer);
            if (editor._creating_type === 'point' && e.layer._latlng !== undefined) {
                layer.enableEdit();
                layer.editor._resizeLatLng.__vertex._icon.style.display = 'none';
            }
            editor._update_editing();
            const form = $('#sidebar').find('.content').find('form.creation-lock');
            form.removeClass('creation-lock')
            if (editor._creating_type !== 'multipoint') {
                if ($('#responsive_switch').is(':visible')) {
                    $('#show_details').click();
                } else {
                    form.find('input:not([type=hidden], .btn)').first().focus();
                }
            }
        }
    },
    _update_editing: function () {
        // called if the temporary drawing layer changes. if we are in editing mode (not creating), update the form.
        if (editor._editing_layer !== null) {
            $('#id_geometry').val(JSON.stringify(editor._editing_layer.toGeoJSON().geometry));
        }
    },

    init_scancollector: function () {
        // init geometries and edit listeners
        editor._highlight_layer = L.layerGroup().addTo(editor.map);

        $('#sidebar').on('click', '.scancollector .start', editor._scancollector_start)
            .on('click', '.scancollector .stop', editor._scancollector_stop)
            .on('click', '.scancollector .reset', editor._scancollector_reset);
        window.setInterval(editor._scancollector_wifi_scan_perhaps, 1000);
    },
    _scancollector_lookup: {},
    load_scancollector_lookup: function () {
        c3nav_api.get('editor/beacons-lookup')
            .then(data => {
                editor._scancollector_lookup = data;
            })
    },
    _scancollector_data: {
        wifi: [],
        ibeacon: [],
    },
    _scancollector_start: function () {
        var $collector = $('#sidebar').find('.scancollector');
        $collector.removeClass('empty').addClass('running');
        editor._scancollector_data.wifi = [];
        editor._scancollector_data.ibeacon = [];
        $collector.find('.wifi-count').text(0);
        $collector.find('.ibeacon-count').text(0);
        if (mobileclient.wificollectorStart) mobileclient.wificollectorStart();
        if (mobileclient.registerBeaconUuid) mobileclient.registerBeaconUuid("a142621a-2f42-09b3-245b-e1ac6356e9b0");
    },
    _scancollector_stop: function () {
        if (mobileclient.wificollectorStop) mobileclient.wificollectorStop();
        if (mobileclient.unregisterBeaconUuid) mobileclient.unregisterBeaconUuid("a142621a-2f42-09b3-245b-e1ac6356e9b0");
        // todo: maybe reset if either is empty?
        if (!editor._scancollector_data.wifi.length && editor._scancollector_data.ibeacon.length) return editor._scancollector_reset();
        var $collector = $('#sidebar').find('.scancollector');
        $collector.removeClass('running').delay(1000).queue(function (n) {
            $(this).addClass('done');
            n();
        });
        $collector.closest('form').removeClass('scan-lock');
    },
    _scancollector_reset: function () {
        var $collector = $('#sidebar').find('.scancollector');
        $collector.removeClass('done').removeClass('running').addClass('empty').find('table tbody').each(function (elem) {
            elem.innerHTML = "";
        });
        $collector.siblings('[name=data]').val('');
        $collector.closest('form').addClass('scan-lock');
        editor._beacon_layer.clearLayers();
    },
    _scancollector_wifi_last_max_last: 0,
    _scancollector_wifi_last_result: 0,
    _scancollector_wifi_result: function (data) {
        var $collector = $('#sidebar').find('.scancollector.running'),
            $table = $collector.find('.wifi-table tbody'),
            item, i, line, apid, color, max_last = 0, now = Date.now(), match;
        editor._wifi_scan_waits = false;

        if (!data.length) return;
        if (now - 2000 < editor._scancollector_wifi_last_result) return;
        editor._scancollector_wifi_last_result = now;

        // ignore this scan?
        for (i = 0; i < data.length; i++) {
            item = data[i];
            if (item.last) {
                max_last = Math.max(max_last, item.last);
            }
        }
        if (max_last && editor._scancollector_wifi_last_max_last && max_last === editor._max_last_max) return;
        editor._scancollector_wifi_last_max_last = max_last;

        $table.find('tr').addClass('old');
        for (i = 0; i < data.length; i++) {
            item = data[i];
            // App version < 4.2.4 use level instead fo rssi
            if (item.level !== undefined) {
                item.rssi = item.level;
                delete item.level
            }

            if (item.rtt !== undefined) {
                item.distance = item.rtt.distance_mm / 1000;
                item.distance_sd = item.rtt.distance_std_dev_mm / 1000;
                delete item.rtt;
            }

            apid = 'ap-' + item.bssid.replace(/:/g, '-');
            line = $table.find('tr.' + apid);
            color = Math.max(0, Math.min(50, item.rssi + 80));
            color = 'rgb(' + String(250 - color * 5) + ', ' + String(color * 4) + ', 0)';
            if (line.length) {
                line.removeClass('old').find(':last-child').text(item.rssi).css('color', color);
            } else {
                match = editor._scancollector_lookup.wifi_beacons?.[item.bssid];
                if (match && match.point) {
                    L.geoJson(match.point, {
                        pointToLayer: function (feature, latlng) {
                            return L.circleMarker(latlng, {});
                        }
                    }).addTo(editor._beacon_layer);
                }
                shortened_ssid = item.ssid;
                if (shortened_ssid.length > 20) {
                    shortened_ssid = shortened_ssid.slice(0, 20) + '…';
                }
                line = $('<tr>').addClass(apid);
                line.append($('<td>').text(item.bssid));
                line.append($('<td>').text(shortened_ssid));
                line.append($('<td>').text(match ? match.name : ''));
                line.append($('<td>').text(item.rssi).css('color', color));
                $table.append(line);
            }
        }
        editor._scancollector_data.wifi.push(data);
        $collector.find('.wifi-count').text(editor._scancollector_data.wifi.length);
        $collector.siblings('[name=data]').val(JSON.stringify(editor._scancollector_data));
        $collector.siblings('[name=data]').text(JSON.stringify(editor._scancollector_data));
    },
    _scancollector_ibeacon_result: function (data) {
        var $collector = $('#sidebar').find('.scancollector.running'),
            $table = $collector.find('.ibeacon-table tbody'),
            item, i, line, beaconid, color = Date.now(), match;

        if (!data.length) return;

        $table.find('tr').addClass('old');
        for (i = 0; i < data.length; i++) {
            item = data[i];
            beaconid = 'beacon-' + item.uuid + '-' + item.major + '-' + item.minor;
            line = $table.find('tr.' + beaconid);
            color = Math.max(0, Math.min(50, item.distance));
            color = 'rgb(' + String(color * 5) + ', ' + String(200 - color * 4) + ', 0)';
            if (line.length) {
                line.removeClass('old').find(':last-child').text(Math.round(item.distance * 100) / 100).css('color', color);
            } else {
                match = editor._scancollector_lookup.ibeacons?.[item.uuid]?.[item.major]?.[item.minor];
                if (match && match.point) {
                    L.geoJson(match.point, {
                        pointToLayer: function (feature, latlng) {
                            return L.circleMarker(latlng, {});
                        }
                    }).addTo(editor._beacon_layer);
                }
                line = $('<tr>').addClass(beaconid);
                line.append($('<td>').text(item.major));
                line.append($('<td>').text(item.minor));
                line.append($('<td>').text(match ? match.name : ''));
                line.append($('<td>').text(Math.round(item.distance * 100) / 100).css('color', color));
                $table.append(line);
            }
        }
        editor._scancollector_data.ibeacon.push(data);
        $collector.find('.ibeacon-count').text(editor._scancollector_data.ibeacon.length);
        $collector.siblings('[name=data]').val(JSON.stringify(editor._scancollector_data));
        $collector.siblings('[name=data]').text(JSON.stringify(editor._scancollector_data));
    },
    _wifi_scan_waits: false,
    _scancollector_wifi_scan_perhaps: function () {
        if (!editor._wifi_scan_waits && $('#sidebar').find('.scancollector.running').length) {
            editor._wifi_scan_waits = true;
            mobileclient.scanNow();
        }
    },

    // Staircase editing functionality

    _setup_staircase_editing: function() {
        editor._staircase_steps_count = 10;
        editor._staircase_layer = L.layerGroup().addTo(editor.map);
        $('#stairway-steps').on('input', function() {
            editor._staircase_steps_count = parseInt($(this).val()) || 10;
            editor._update_staircase_preview();
        });

        editor.map.on('editable:editing', editor._update_staircase_preview);
    },

    _destroy_staircase_editing: function() {
        if (editor._staircase_layer) {
            editor.map.removeLayer(editor._staircase_layer);
            editor._staircase_layer = null;
        }
        editor.map.off('editable:editing', editor._update_staircase_preview);
        if (editor._current_editing_shape && editor._current_editing_shape.editor) {
            editor._current_editing_shape.editor.cancelDrawing();
            editor._current_editing_shape.remove();
            editor._current_editing_shape = null;
        }
    },

    _transform_point_for_staircase: function(p, p0, cos_a, sin_a) {
        return {
            x: + (p.x - p0.x) * cos_a + (p.y - p0.y) * sin_a + p0.x,
            y: - (p.x - p0.x) * sin_a + (p.y - p0.y) * cos_a + p0.y,
        };
    },

    _transform_for_staircase: function(xs, ys, num_stairs) {
        let base_length = Math.sqrt((xs[1]-xs[0])**2 + (ys[1]-ys[0])**2);
        let cos_a = (xs[1] - xs[0]) / base_length;
        let sin_a = (ys[1] - ys[0]) / base_length;
        let p0 = { x: xs[0], y: ys[0] };

        xs = points.map(p => editor._transform_point_for_staircase(p, p0, cos_a, sin_a).x);
        ys = points.map(p => editor._transform_point_for_staircase(p, p0, cos_a, sin_a).y);
        n = xs.length;

        if (Math.abs(Math.max(...ys) - ys[0]) > Math.abs(Math.min(...ys) - ys[0])) {
            height = Math.max(...ys) - ys[0];
        } else {
            height = Math.min(...ys) - ys[0];
        }

        // If the user aligns the staircase creation polygon to an edge of a Space (supposedly the
        // Space representing the stairwell), we need to ensure that the stairs' lines overflow a
        // bit, otherwise they won't get picked up by the map rendering algorithm (which may see a
        // stair that doesn't split the Space into two parts and gets confused).
        // Hence the -X_OVERFLOW and +X_OVERFLOW; X_OVERFLOW = '2 units' seemed reasonable.
        const X_OVERFLOW = 2;
        lines = [{p1: { x: xs[0]-X_OVERFLOW, y: ys[0] }, p2: { x: xs[1]+X_OVERFLOW, y: ys[1] }}];
        for (i = 1; i < num_stairs; ++i) {
            // intersect line y=y0+height/num_stairs*i with all transformed (xs,ys)
            y = ys[0] + height/num_stairs*i;
            inters_xs = [];
            for (j = 0; j < n; ++j) {
                y1 = ys[j];
                y2 = ys[(j+1)%n];
                x1 = xs[j];
                x2 = xs[(j+1)%n];
                if ((y1 > y && y2 > y) || (y1 < y && y2 < y)) {
                    continue;
                }

                if (Math.abs(x2 - x1) < 0.0001) {
                    // vertical line, m would be infinity
                    inters_xs.push(x1);
                    continue;
                }

                m = (y2 - y1) / (x2 - x1);
                q = y2 - m * x2;
                inters_xs.push((y - q) / m);
            }

            if (inters_xs.length < 2) {
                continue;
            }

            min_xs = Math.min(...inters_xs);
            max_xs = Math.max(...inters_xs);
            lines.push({p1: {x: min_xs-X_OVERFLOW, y: y}, p2: {x: max_xs+X_OVERFLOW, y: y}});
        }

        lines = lines.map(l => ({
            p1: editor._transform_point_for_staircase(l.p1, p0, cos_a, -sin_a),
            p2: editor._transform_point_for_staircase(l.p2, p0, cos_a, -sin_a),
        }));

        return lines;
    },

    _get_staircase_lines: function() {
        if (!editor._current_editing_shape || !editor._current_editing_shape._parts) {
            return [];
        }
        points = editor._current_editing_shape._parts[0] || [];
        if (points.length < 3) {
            return [];
        }

        xs = points.map(p => p.x);
        ys = points.map(p => p.y);
        lines = editor._transform_for_staircase(xs, ys, editor._staircase_steps_count);
        lines = lines.map(l => [
            editor.map.layerPointToLatLng([l.p1.x, l.p1.y]),
            editor.map.layerPointToLatLng([l.p2.x, l.p2.y]),
        ]);
        return lines;
    },

    _update_staircase_preview: function(e = null) {
        if (editor._staircase_layer) {
            editor._staircase_layer.clearLayers();
        }
        lines = editor._get_staircase_lines();
        lines.forEach(l => {
            L.polyline(l, {color: "red"}).addTo(editor._staircase_layer);
        });
    },

    _staircase_submit: function(form) {
        csrfmiddlewaretoken = form.find('input[name=csrfmiddlewaretoken]').attr('value');
        import_tag = form.find('input[name=import_tag]').val();
        space = form.attr('space');
        lines = editor._get_staircase_lines();

        save_stair = l => fetch("/editor/spaces/" + space + "/stairs/create", {
            method: "POST",
            headers: {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            },
            body: "csrfmiddlewaretoken=" + encodeURIComponent(csrfmiddlewaretoken) +
                "&geometry=" + encodeURIComponent(JSON.stringify({
                    type: "LineString",
                    coordinates: [[l[0]["lng"], l[0]["lat"]], [l[1]["lng"], l[1]["lat"]]]
                })) +
                "&import_tag=" + encodeURIComponent(import_tag),
        });

        complete_redirect = () => {
            form.remove();
            window.location.href = "/editor/spaces/" + space + "/stairs";
        };

        if (lines.length === 0) {
            complete_redirect();
        } else {
            let first = lines.shift();
            // save one stair first, so a changeset is created if there is not already one
            save_stair(first).then(() => {
                // then save the remaining stairs all at once, ending up in the changeset
                Promise.all(lines.map(save_stair))
                    .then(complete_redirect);
            });
        }
    }
};

function nearby_stations_available() {
    editor._scancollector_wifi_result(JSON.parse(mobileclient.getNearbyStations()));
}

function ibeacon_results_available() {
    editor._scancollector_ibeacon_result(JSON.parse(mobileclient.getNearbyBeacons()));
}

LevelControl = L.Control.extend({
    options: {
        position: 'bottomright',
        addClasses: ''
    },

    onAdd: function () {
        this._container = L.DomUtil.create('div', 'leaflet-control-levels leaflet-bar ' + this.options.addClasses);
        this._levelButtons = [];
        //noinspection JSUnusedGlobalSymbols
        this.current_level_id = null;
        this.level_ids = [];
        this._disabled = true;
        this._expanded = false;
        this.geometryURLs = false;
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

    clearLevels: function () {
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
            if (this.geometryURLs) {
                editor.load_geometries(
                    e.target.href,
                    editor._highlight_type,
                    editor._editing_id
                );
            } else {
                editor._next_zoom = false;
                editor.sidebar_get(e.target.href);
            }
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

OverlayControl = L.Control.extend({
    options: {position: 'topright', addClasses: ''},
    _overlays: {},
    _groups: {},
    _initialActiveOverlays: null,
    _initialCollapsedGroups: null,

    onAdd: function () {
        this._initialActiveOverlays = JSON.parse(localStorage.getItem('c3nav.editor.overlays.active-overlays') ?? '[]');
        this._initialCollapsedGroups = JSON.parse(localStorage.getItem('c3nav.editor.overlays.collapsed-groups') ?? '[]');
        const pinned = JSON.parse(localStorage.getItem('c3nav.editor.overlays.pinned') ?? 'false');

        this._container = L.DomUtil.create('div', 'leaflet-control-overlays ' + this.options.addClasses);
        this._container.classList.toggle('leaflet-control-overlays-expanded', pinned);
        this._content = L.DomUtil.create('div', 'content');
        const collapsed = L.DomUtil.create('div', 'collapsed-toggle leaflet-control-layers-toggle');
        this._pin = L.DomUtil.create('div', 'pin-toggle');
        this._pin.classList.toggle('active', pinned);
        this._pin.innerText = '🖈';
        this._container.append(this._pin, this._content, collapsed);
        this._expanded = pinned;
        this._pinned = pinned;

        if (!L.Browser.android) {
            L.DomEvent.on(this._container, {
                mouseenter: this.expand,
                mouseleave: this.collapse
            }, this);
        }

        if (!L.Browser.touch) {
            L.DomEvent.on(this._container, 'focus', this.expand, this);
            L.DomEvent.on(this._container, 'blur', this.collapse, this);
        }

        for (const overlay of this._initialActiveOverlays) {
            if (overlay in this._overlays) {
                this._overlays[overlay].visible = true;
                this._overlays[overlay].layer.addTo(this._map);
            }
        }

        for (const group of this._initialCollapsedGroups) {
            if (group in this._groups) {
                this._groups[group].expanded = false;
            }
        }

        this.render();

        $(this._container).on('change', 'input[type=checkbox]', e => {
            this._overlays[e.target.dataset.source].visible = e.target.checked;
            this.updateOverlay(e.target.dataset.source);
        });
        $(this._container).on('click', 'div.pin-toggle', e => {
            this.togglePinned();
        });
        $(this._container).on('click', '.content h4', e => {
            this.toggleGroup(e.target.parentElement.dataset.group);
        });
        $(this._container).on('mousedown pointerdown wheel', e => {
            e.stopPropagation();
        });
        return this._container;
    },

    addOverlay: function (layer, name, group) {
        const l = {
            layer,
            name,
            group,
            visible: this._initialActiveOverlays !== null && this._initialActiveOverlays.includes(name),
        };
        this._overlays[name] = l;
        if (group in this._groups) {
            this._groups[group].overlays.push(l);
        } else {
            this._groups[group] = {
                expanded: this._initialCollapsedGroups === null || !this._initialCollapsedGroups.includes(group),
                overlays: [l],
            };
        }
        this.render();
    },

    updateOverlay: function (id) {
        const overlay = this._overlays[id];
        if (overlay.visible) {
            overlay.layer.addTo(this._map);
        } else {
            this._map.removeLayer(overlay.layer);
        }
        const activeOverlays = Object.keys(this._overlays).filter(k => this._overlays[k].visible);
        localStorage.setItem('c3nav.editor.overlays.active-overlays', JSON.stringify(activeOverlays));
    },

    render: function () {
        if (!this._content) return;
        const groups = document.createDocumentFragment();
        for (const group in this._groups) {
            const group_container = document.createElement('div');
            group_container.classList.add('overlay-group');
            if (this._groups[group].expanded) {
                group_container.classList.add('expanded');
            }
            this._groups[group].el = group_container;
            group_container.dataset.group = group;
            const title = document.createElement('h4');
            title.innerText = group;
            group_container.append(title);
            for (const overlay of this._groups[group].overlays) {
                const label = document.createElement('label');
                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.dataset.source = overlay.name;
                if (overlay.visible) {
                    checkbox.checked = true;
                }
                label.append(checkbox, overlay.name);
                group_container.append(label);
            }
            groups.append(group_container);
        }
        this._content.replaceChildren(...groups.children);
    },

    expand: function () {
        if (this._pinned) return;
        this._expanded = true;
        this._container.classList.add('leaflet-control-overlays-expanded');
        return this;
    },

    collapse: function () {
        if (this._pinned) return;
        this._expanded = false;
        this._container.classList.remove('leaflet-control-overlays-expanded');
        return this;
    },

    toggleGroup: function (name) {
        const group = this._groups[name];
        group.expanded = !group.expanded;
        group.el.classList.toggle('expanded', group.expanded);
        const collapsedGroups = Object.keys(this._groups).filter(k => !this._groups[k].expanded);
        localStorage.setItem('c3nav.editor.overlays.collapsed-groups', JSON.stringify(collapsedGroups));
    },

    togglePinned: function () {
        this._pinned = !this._pinned;
        if (this._pinned) {
            this._expanded = true;
        }
        this._pin.classList.toggle('active', this._pinned);
        localStorage.setItem('c3nav.editor.overlays.pinned', JSON.stringify(this._pinned));
    },
});

if ($('#sidebar').length) {
    editor.init();
}
