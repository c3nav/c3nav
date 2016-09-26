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

        L.control.scale({imperial: false}).addTo(editor.map);
        editor._highlight_layer = L.layerGroup().addTo(editor.map);

        editor.get_feature_types();
        editor.get_packages();
        editor.get_sources();
    },

    get_feature_types: function () {
        $.getJSON('/api/v1/featuretypes/', function (feature_types) {
            var feature_type;
            var editcontrols = $('#mapeditlist');
            for (var i = 0; i < feature_types.length; i++) {
                feature_type = feature_types[i];
                editor.feature_types[feature_type.name] = feature_type;
                editor.feature_types_order.push(feature_type.name);
                editcontrols.append(
                    $('<fieldset class="feature_list">').attr('name', feature_type.name).append(
                        $('<legend>').text(feature_type.title_plural).append(
                            $('<button class="btn btn-default btn-xs pull-right start-drawing"><i class="glyphicon glyphicon-plus"></i></button>')
                        )
                    )
                );
            }
            editor.get_levels();
        });
    },

    packages: {},
    get_packages: function () {
        $.getJSON('/api/v1/packages/', function (packages) {
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

    sources: {},
    get_sources: function () {
        $.getJSON('/api/v1/sources/', function (sources) {
            var layers = {};
            var source;
            for (var i = 0; i < sources.length; i++) {
                source = sources[i];
                editor.sources[source.name] = source;
                source.layer = L.imageOverlay('/api/v1/sources/' + source.name + '/image/', source.bounds);
                layers[source.name] = source.layer;
            }
            L.control.layers([], layers).addTo(editor.map);
        });
    },

    levels: {},
    _level: null,
    level_feature_layers: {},
    get_levels: function () {
        $.getJSON('/api/v1/levels/?ordering=-altitude', function (levels) {
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

            var level, feature_type;
            for (var i = 0; i < levels.length; i++) {
                level = levels[i];
                editor.levels[level.name] = level;
                editor.level_feature_layers[level.name] = {};
                for (var j = 0; j < editor.feature_types_order.length; j++) {
                    feature_type = editor.feature_types_order[j];
                    editor.level_feature_layers[level.name][feature_type] = L.layerGroup();
                    $('.feature_list[name='+feature_type+']').append(
                        $('<ul class="feature_level_list">').attr('data-level', level.name)
                    );
                }
            }
            editor.set_current_level(levels[levels.length - 1].name);
            editor.init_features();
        });
    },
    set_current_level: function(level_name) {
        if (editor._creating !== null || editor._editing !== null) return;
        for (var i = 0; i < editor.feature_types_order.length; i++) {
            if (editor._level !== null) {
                editor.level_feature_layers[editor._level][editor.feature_types_order[i]].remove();
            }
            editor.level_feature_layers[level_name][editor.feature_types_order[i]].addTo(editor.map);
        }
        editor._level = level_name;
        $('.leaflet-levels .current').removeClass('current');
        $('.leaflet-levels a[name='+level_name+']').addClass('current');
        $('.feature_level_list').hide();
        $('.feature_level_list[data-level='+level_name+']').show();
    },

    _creating: null,
    _editing: null,
    init_features: function () {
        // Add drawing new features
        L.DrawControl = L.Control.extend({
            options: {
                position: 'topleft'
            },
            onAdd: function () {
                var container = L.DomUtil.create('div', 'leaflet-control leaflet-bar leaflet-drawbar');
                $('<a href="#" id="drawcancel">').appendTo(container).text('cancel').attr({
                    href: '#',
                    title: 'cancel drawing',
                    name: ''
                }).on('click', function (e) {
                    e.preventDefault();
                    editor.cancel_creating();
                });
                return container;
            }
        });
        editor.map.addControl(new L.DrawControl());

        $('#mapeditlist').on('click', '.start-drawing', editor._click_start_drawing)
                         .on('mouseenter', '.feature_level_list li', editor._hover_feature_detail)
                         .on('mouseleave', '.feature_level_list li', editor._unhover_feature_detail)
                         .on('click', '.feature_level_list li', editor._click_feature_detail);

        editor.map.on('editable:drawing:commit', editor.done_creating);
        editor.map.on('editable:editing', editor.update_editing);
        editor.map.on('editable:drawing:cancel', editor._canceled_creating);

        $('#mapeditdetail').on('click', '#btn_editing_cancel', editor.cancel_editing)
                           .on('click', 'button[type=submit]', editor.submit_editing_btn_click)
                           .on('submit', 'form', editor.submit_editing)


        editor.get_features();
    },

    features: {},
    get_features: function () {
        $.getJSON('/api/v1/features/', function(features) {
            var feature_type;
            for (var level in editor.levels) {
                for (var j = 0; j < editor.feature_types_order.length; j++) {
                    feature_type = editor.feature_types_order[j];
                    editor.level_feature_layers[level][feature_type].clearLayers();
                }
            }
            $('.feature_level_list li').remove();
            var feature, layergroup;
            for (var i=0; i < features.length; i++) {
                feature = features[i];
                layergroup = L.geoJSON({
                    type: 'Feature',
                    geometry: feature.geometry,
                    properties: {
                        name: feature.name,
                        feature_type: feature.feature_type
                    }
                }, {
                    style: editor._get_feature_style
                }).on('mouseover', editor._hover_feature_layer)
                  .on('mouseout', editor._unhover_feature_layer)
                  .on('click', editor._click_feature_layer)
                  .addTo(editor.level_feature_layers[feature.level][feature.feature_type]);
                feature.layer = layergroup.getLayers()[0];
                editor.features[feature.name] = feature;

                $('.feature_list[name='+feature.feature_type+'] > [data-level='+feature.level+']').append(
                    $('<li>').attr('name', feature.name).append(
                        $('<p>').text(feature.title).append(' ').append(
                            $('<em>').text(feature.name)
                        )
                    )
                );
            }
            $('.start-drawing').show();
            $('#mapeditcontrols').addClass('list');
            editor.set_current_level(editor._level);
        });
    },
    _get_feature_style: function (feature) {
        return editor.feature_types[feature.properties.feature_type];
    },

    _click_start_drawing: function (e) {
        editor.start_creating($(this).closest('fieldset').attr('name'));
    },
    _hover_feature_detail: function (e) {
        editor._highlight_layer.clearLayers();
        L.geoJSON(editor.features[$(this).attr('name')].geometry, {
            style: function() {
                return {
                    color: '#FFFFEE',
                    opacity: 0.5,
                    fillOpacity: 0.5,
                    className: 'c3nav-highlight'
                };
            }
        }).addTo(editor._highlight_layer);
    },
    _unhover_feature_detail: function () {
        editor._highlight_layer.clearLayers();
    },
    _click_feature_detail: function() {
        editor.start_editing($(this).attr('name'));
    },

    _hover_feature_layer: function (e) {
        editor._unhover_feature_layer();
        if (editor._editing === null && editor._creating === null) {
            editor._highlight_layer.clearLayers();
            L.geoJSON(e.layer.toGeoJSON(), {
                style: function() {
                    return {
                        color: '#FFFFEE',
                        opacity: 0.5,
                        fillOpacity: 0.5,
                        className: 'c3nav-highlight'
                    };
                }
            }).addTo(editor._highlight_layer);
        }
        $('.feature_list li[name='+e.layer.feature.properties.name+']').addClass('hover');
    },
    _unhover_feature_layer: function (e) {
        editor._highlight_layer.clearLayers();
        $('.feature_list .hover').removeClass('hover');
    },
    _click_feature_layer: function(e) {
        editor.start_editing(e.layer.feature.properties.name);
        if ((e.originalEvent.ctrlKey || e.originalEvent.metaKey) && this.editEnabled()) {
            if (e.layer.feature.properties.geomtype == 'polygon') {
                this.editor.newHole(e.latlng);
            }
        }
    },

    start_creating: function (feature_type) {
        if (editor._creating !== null || editor._editing !== null) return;
        editor._highlight_layer.clearLayers();
        editor._creating = feature_type;
        var options = editor.feature_types[feature_type];
        if (options.geomtype == 'polygon') {
            editor.map.editTools.startPolygon(null, options);
        } else if (options.geomtype == 'polyline') {
            editor.map.editTools.startPolyline(null, options);
        }
        $('.leaflet-drawbar').show();
        $('.start-drawing').hide();
    },
    cancel_creating: function () {
        if (editor._creating === null || editor._editing !== null) return;
        editor.map.editTools.stopDrawing();
        editor._creating = null;
        $('.leaflet-drawbar').hide();
    },
    _canceled_creating: function (e) {
        if (editor._creating !== null && editor._editing === null) {
            e.layer.remove();
            $('.start-drawing').show();
        }
    },
    done_creating: function(e) {
        if (editor._creating !== null && editor._editing === null) {
            editor._editing = e.layer;
            editor._editing.disableEdit();
            editor.map.fitBounds(editor._editing.getBounds());

            $('.leaflet-drawbar').hide();
            var path = '/editor/features/' + editor._creating + '/add/';
            $('#mapeditcontrols').removeClass('list');
            $('#mapeditdetail').load(path, editor.edit_form_loaded);
        }
    },

    start_editing: function (name) {
        if (editor._creating !== null || editor._editing !== null) return;
        editor._highlight_layer.clearLayers();
        editor._editing = editor.features[name].layer;
        var path = '/editor/features/edit/' + name + '/';
        $('#mapeditcontrols').removeClass('list');
        $('#mapeditdetail').load(path, editor.edit_form_loaded);
    },
    edit_form_loaded: function() {
        $('#mapeditcontrols').addClass('detail');
        $('#id_level').val(editor._level);
        $('#id_geometry').val(JSON.stringify(editor._editing.toGeoJSON().geometry));
        editor._editing.enableEdit();
        if (editor._editing.options.geomtype == 'polygon') {
            editor._editing.on('click', function (e) {
                if ((e.originalEvent.ctrlKey || e.originalEvent.metaKey) && this.editEnabled()) {
                    this.editor.newHole(e.latlng);
                }
            });
        }
    },
    update_editing: function () {
        if (editor._editing !== null) {
            $('#id_geometry').val(JSON.stringify(editor._editing.toGeoJSON().geometry));
        }
    },
    cancel_editing: function() {
        if (editor._editing !== null) {
            if (editor._creating !== null) {
                editor._editing.remove();
            }
            editor._editing = null;
            editor._creating = null;
            $('#mapeditcontrols').removeClass('detail');
            $('#mapeditdetail').html('');
            editor.get_features();
        }
    },
    submit_editing_btn_click: function(e) {
        $(this).closest('form').data('btn', $(this)).clearQueue().delay(300).queue(function() {
            $(this).data('button', null);
        });
    },
    submit_editing: function(e) {
        e.preventDefault();
        var data = $(this).serialize();
        var btn = $(this).data('btn');
        if (btn !== undefined && btn !== null && $(btn).is('[name]')) {
            data += '&'+$('<input>').attr('name', $(btn).attr('name')).val($(btn).val()).serialize();
        }
        var action = $(this).attr('action');
        $('#mapeditcontrols').removeClass('detail');
        $('#mapeditdetail').html('');
        editor._editing.disableEdit();
        $.post(action, data, function (data) {
            var content = $(data);
            if ($('<div>').append(content).find('form').length > 0) {
                $('#mapeditdetail').html(content);
                $('#mapeditcontrols').addClass('detail');
                editor._editing.enableEdit();
            } else {
                if (editor._creating !== null) {
                    editor._editing.remove();
                }
                editor._editing = null;
                editor._creating = null;
                editor.get_features();
            }
        });
    }
};


if ($('#mapeditlist').length) {
    editor.init();
}
