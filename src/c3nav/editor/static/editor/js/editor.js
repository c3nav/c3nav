editor = {
    feature_types: {},
    feature_types_order: [],

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
                    $('<fieldset>').attr('name', feature_type.name).append(
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

            var level;
            for (var i = 0; i < levels.length; i++) {
                level = levels[i];
                editor.levels[level.name] = level;
                editor.level_feature_layers[level.name] = {};
                for (var j = 0; j < editor.feature_types_order.length; j++) {
                    editor.level_feature_layers[level.name][editor.feature_types_order[j]] = L.layerGroup();
                }
            }
            editor.set_current_level(levels[levels.length - 1].name);
            editor.init_drawing();
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
    },

    _creating: null,
    _editing: null,
    init_drawing: function () {
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

        $('#mapeditlist').on('click', '.start-drawing', function () {
            editor.start_creating($(this).closest('fieldset').attr('name'));
        });

        editor.map.on('editable:drawing:commit', editor.done_creating);
        editor.map.on('editable:editing', editor.update_editing);
        editor.map.on('editable:drawing:cancel', editor._canceled_creating);

        $('#mapeditdetail').on('click', '#btn_editing_cancel', editor.cancel_editing)
                           .on('submit', 'form', editor.submit_editing);

        editor.get_features();
    },

    get_features: function () {
        $.getJSON('/api/v1/features/', function(features) {
            for (level in editor.level_layers) {
                editor.level_layers[level].clearLayers();
            }
            var feature;
            for (var i=0; i < features.length; i++) {
                feature = features[i];
                L.geoJSON({
                    type: 'Feature',
                    geometry: feature.geometry,
                    properties: {
                        name: feature.name,
                        feature_type: feature.feature_type
                    }
                }, {
                    style: editor._get_feature_style
                }).addTo(editor.level_feature_layers[feature.level][feature.feature_type]);
            }
            $('.start-drawing').show();
            $('#mapeditcontrols').addClass('list');
            editor.set_current_level(editor._level);
        });

    },
    _get_feature_style: function (feature) {
        return editor.feature_types[feature.properties.feature_type];
    },

    start_creating: function (feature_type) {
        if (editor._creating !== null || editor._editing !== null) return;
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

    start_editing: function () {
        // todo
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
    submit_editing: function(e) {
        e.preventDefault();
        var data = $(this).serialize();
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
