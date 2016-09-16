editor = {
    feature_types: {
        bounds: {
            type: 'polygon',
            color: '#FFFFFF',
        },
        building: {
            type: 'polygon',
            color: '#CCCCCC',
        },
        wall: {
            type: 'polygon',
            color: '#333333',
        },
        obstacle: {
            type: 'polygon',
            color: '#999999',
        },
        door: {
            type: 'polygon',
            color: '#FF00FF',
        },
        step: {
            type: 'polyline',
            color: '#FF0000',
        },
        elevator: {
            type: 'polygon',
            color: '#99CC00',
        },
    },

    init: function() {
        // Init Map
        editor.map = L.map('mapeditor', {
            zoom: 2,
            maxZoom: 10,
            minZoom: 1,
            crs: L.CRS.Simple,
            editable: true,
            closePopupOnClick: false,
        });

        L.control.scale({imperial: false}).addTo(editor.map);

        editor.get_packages();
        editor.init_features();
    },

    init_features: function() {
        editor._feature_type = null;
        L.FeatureLayerControl = L.Control.extend({
            options: {
                position: 'topleft'
            },
            onAdd: function (map) {
                var container = L.DomUtil.create('div', 'leaflet-control leaflet-bar leaflet-editbar usable');
                $('<a href="#" class="current">').appendTo(container).html('').attr({
                    href: '#',
                    title: 'disable editing',
                    name: 'null'
                }).on('click', function() {
                    editor.set_feature_type(null);
                });
                var plural;
                for (var feature_type in editor.feature_types) {
                    $('<a href="#">').appendTo(container).text(feature_type+((feature_type.substr(-1) != 's')?'s':'')).attr({
                        href: '#',
                        title: 'edit '+feature_type+' layer',
                        name: feature_type
                    }).on('click', editor._layer_button_click);
                }
                return container;
            }
        });
        editor.map.addControl(new L.FeatureLayerControl());

        // Add drawing new features
        editor._drawing = null;
        editor._adding = null;

        L.DrawControl = L.Control.extend({
            options: {
                position: 'topleft'
            },
            onAdd: function (map) {
                var container = L.DomUtil.create('div', 'leaflet-control leaflet-bar leaflet-drawbar');
                $('<a href="#" id="drawstart">').appendTo(container).text('start drawing').attr({
                    href: '#',
                    title: 'start drawing',
                    name: ''
                }).on('click', function(e) {
                    e.preventDefault();
                    editor.start_drawing();
                });

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
        $('#drawcancel').hide();

        editor.map.on('editable:drawing:commit', function (e) {
            editor._drawing = null;
            editor._adding = e.layer;

            e.layer.disableEdit();
            L.popup({
                closeButton: false,
                autoClose: false,
            }).setContent('<img src="/static/img/loader.gif">').setLatLng(e.layer.getCenter()).openOn(editor.map);
            console.log(e.layer.toGeoJSON());
        }).on('editable:drawing:cancel', function (e) {
            if (editor._drawing !== null && editor._adding === null) {
                e.layer.remove();
            }
        });
    },

    _layer_button_click: function(e) {
        e.preventDefault();
        editor.set_feature_type($(this).attr('name'));
    },

    set_feature_type: function(feature_type) {
        if (editor._drawing !== null || editor._adding !== null) return;

        $('.leaflet-editbar .current').removeClass('current');
        $('.leaflet-editbar [name='+feature_type+']').addClass('current');
        editor._feature_type = feature_type;

        $('.leaflet-drawbar').toggle(feature_type !== null);
        $('#drawstart').text('add '+feature_type);
    },
    start_drawing: function() {
        if (editor._feature_type === null) return;

        editor._drawing = editor._feature_type;
        var options = editor.feature_types[editor._drawing];
        if (options.type == 'polygon') {
            editor.map.editTools.startPolygon(null, options);
        } else if (options.type == 'polyline') {
            editor.map.editTools.startPolyline(null, options);
        }
        $('.leaflet-editbar').toggleClass('usable', false);
        $('#drawstart').hide();
        $('#drawcancel').show();
    },
    cancel_drawing: function() {
        if (editor._drawing === null || editor._adding !== null) return;
        editor.map.editTools.stopDrawing();
        editor._drawing = null;
        $('.leaflet-editbar').toggleClass('usable', true);
        $('#drawcancel').hide();
        $('#drawstart').show();
    },

    get_packages: function() {
        $.getJSON('/api/v1/packages/', function(packages) {
            var bounds = [[0, 0], [0, 0]];
            var pkg;
            for(var i=0;i<packages.length;i++) {
                pkg = packages[i];
                if (pkg.bounds === null) continue;
                bounds = [[Math.min(bounds[0][0], pkg.bounds[0][0]), Math.min(bounds[0][1], pkg.bounds[0][1])],
                          [Math.max(bounds[1][0], pkg.bounds[1][0]), Math.max(bounds[1][1], pkg.bounds[1][1])]];
            }
            editor.map.setMaxBounds(bounds);
            editor.map.fitBounds(bounds, {padding: [30, 50]});

            editor.get_sources();
            editor.get_levels();
        });
    },
    get_sources: function() {
        $.getJSON('/api/v1/sources/', function(sources) {
            var layers = {};
            var source;
            for(var i=0;i<sources.length;i++) {
                source = sources[i];
                layers[source.name] = L.imageOverlay('/api/v1/sources/'+source.name+'/image/', source.bounds);
            }
            L.control.layers([], layers).addTo(editor.map);
        });
    },
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
        });
    },
};


if ($('#mapeditor').length) {
    editor.init();
}
