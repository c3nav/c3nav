editor = {
    feature_types: {},

    init: function() {
        // Init Map
        editor.map = L.map('map', {
            zoom: 2,
            maxZoom: 10,
            minZoom: 1,
            crs: L.CRS.Simple,
            editable: true,
            closePopupOnClick: false,
        });

        L.control.scale({imperial: false}).addTo(editor.map);

        editor.get_feature_types();
        editor.get_packages();
        editor.get_sources();
        editor.get_levels();
    },

    get_feature_types: function() {
        $.getJSON('/api/v1/featuretypes/', function(feature_types) {
            var feature_type;
            var editcontrols = $('#mapeditcontrols');
            for(var i=0;i<feature_types.length;i++) {
                feature_type = feature_types[i];
                editor.feature_types[feature_type.name] = feature_type;
                editcontrols.append(
                    $('<fieldset>').attr('name', feature_type.name).append(
                        $('<legend>').text(feature_type.title_plural).append(
                            $('<button class="btn btn-default btn-xs pull-right start-drawing"><i class="glyphicon glyphicon-plus"></i></button>')
                        )
                    )
                );
            }
        });
    },

    packages: {},
    get_packages: function() {
        $.getJSON('/api/v1/packages/', function(packages) {
            var bounds = [[0, 0], [0, 0]];
            var pkg;
            for(var i=0;i<packages.length;i++) {
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
    get_sources: function() {
        $.getJSON('/api/v1/sources/', function(sources) {
            var layers = {};
            var source;
            for(var i=0;i<sources.length;i++) {
                source = sources[i];
                editor.sources[source.name] = source;
                source.layer = L.imageOverlay('/api/v1/sources/'+source.name+'/image/', source.bounds);
                layers[source.name] = source.layer;
            }
            L.control.layers([], layers).addTo(editor.map);
        });
    },

    level_layers: {},
    levels: {},
    get_levels: function() {
        $.getJSON('/api/v1/levels/?ordering=-altitude', function(levels) {
            L.LevelControl = L.Control.extend({
                options: {
                    position: 'bottomright'
                },
                onAdd: function (map) {
                    var container = L.DomUtil.create('div', 'leaflet-control leaflet-bar leaflet-levels'), link;
                    var level;
                    for(var i=0;i<levels.length;i++) {
                        level = levels[i];
                        link = L.DomUtil.create('a', (i == levels.length-1) ? 'current' : '', container);
                        link.innerHTML = level.name;
                    }
                    return container;
                }
            });
            editor.map.addControl(new L.LevelControl());

            var level_layer, feature_layer, level;
            for(var i=0;i<levels.length;i++) {
                level = levels[i];
                editor.levels[level.name] = level;
                level_layer = L.layerGroup().addTo(editor.map);
                editor.level_layers[level.name] = level_layer;
            }
            editor.init_drawing();
        });
    },

    init_drawing: function() {
        // Add drawing new features
        editor._drawing = null;
        editor._adding = null;

        L.DrawControl = L.Control.extend({
            options: {
                position: 'topleft'
            },
            onAdd: function (map) {
                var container = L.DomUtil.create('div', 'leaflet-control leaflet-bar leaflet-drawbar');
                $('<a href="#" id="drawcancel">').appendTo(container).text('cancel').attr({
                    href: '#',
                    title: 'cancel drawing',
                    name: ''
                }).on('click', function(e) {
                    e.preventDefault();
                    editor.cancel_drawing();
                });
                return container;
            }
        });
        editor.map.addControl(new L.DrawControl());

        $('#mapeditcontrols').on('click', '.start-drawing', function() {
            console.log($(this).closest('fieldset'));
            editor.start_drawing($(this).closest('fieldset').attr('name'));
        });

        editor.map.on('editable:drawing:commit', function (e) {
            editor._drawing = null;
            editor._adding = e.layer;

            e.layer.disableEdit();
            L.popup({
                closeButton: false,
                autoClose: false,
            }).setContent('<img src="/static/img/loader.gif">').setLatLng(e.layer.getCenter()).openOn(editor.map);
            $('.leaflet-drawbar').hide();
        }).on('editable:drawing:cancel', function (e) {
            if (editor._drawing !== null && editor._adding === null) {
                e.layer.remove();
                $('.start-drawing').prop('disabled', false);
            }
        });
    },

    start_drawing: function(feature_type) {
        if (editor._drawing !== null || editor._adding !== null) return;
        editor._drawing = feature_type;
        var options = editor.feature_types[feature_type];
        if (options.geomtype == 'polygon') {
            editor.map.editTools.startPolygon(null, options);
        } else if (options.geomtype == 'polyline') {
            editor.map.editTools.startPolyline(null, options);
        }
        $('.leaflet-drawbar').show();
        $('.start-drawing').prop('disabled', true);
    },
    cancel_drawing: function() {
        if (editor._drawing === null || editor._adding !== null) return;
        editor.map.editTools.stopDrawing();
        editor._drawing = null;
        $('.leaflet-drawbar').hide();
    },
};


if ($('#mapeditcontrols').length) {
    editor.init();
}
