function add_edit_button(map, container, type, icon, callback) {
    $('<a href="#">').appendTo(container).text(icon).attr({
        href: '#',
        title: 'add '+name,
        name: type
    }).on('click', function(e) {
        e.preventDefault();

        // If we are currently adding a feature, don't start drawing another.
        if (currently_adding !== null) {
            return;
        }

        // If we are currently drawing a feature, don't start drawing another.
        if (currently_drawing !== null) {
            // If it is a feature of the same type, cancel it.
            if (currently_drawing === type) {
                $('.leaflet-editbar .current').removeClass('current');
                currently_drawing = null;
                map.editTools.stopDrawing();
            }
            return;
        }

        currently_drawing = type;
        console.log(type);
        $('.leaflet-editbar .current').removeClass('current');
        $('.leaflet-editbar [name='+type+']').addClass('current');
        options = feature_types[type];
        if (options.type == 'polygon') {
            map.editTools.startPolygon(null, options);
        } else if (options.type == 'polyline') {
            map.editTools.startPolyline(null, options);
        }
    });
}

if ($('#mapeditor').length) {
    // Init Map
    var map = L.map('mapeditor', {
        zoom: 2,
        maxZoom: 10,
        minZoom: 1,
        crs: L.CRS.Simple,
        editable: true,
        closePopupOnClick: false,
    });

    $.getJSON('/api/v1/packages/', function(packages) {
        var bounds = [[0, 0], [0, 0]];
        var pkg;
        for(var i=0;i<packages.length;i++) {
            pkg = packages[i];
            if (pkg.bounds === null) continue;
            bounds = [[Math.min(bounds[0][0], pkg.bounds[0][0]), Math.min(bounds[0][1], pkg.bounds[0][1])],
                      [Math.max(bounds[1][0], pkg.bounds[1][0]), Math.max(bounds[1][1], pkg.bounds[1][1])]];
        }
        map.setMaxBounds(bounds);
        map.fitBounds(bounds, {padding: [30, 50]});

        $.getJSON('/api/v1/sources/', function(sources) {
            var layers = {};
            var source;
            for(var i=0;i<sources.length;i++) {
                source = sources[i];
                layers[source.name] = L.imageOverlay('/api/v1/sources/'+source.name+'/image/', source.bounds);
            }
            L.control.layers([], layers).addTo(map);
        });

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
            map.addControl(new L.LevelControl());
        });
    });

    // Default styles:
    feature_types = {
        building: {
            type: 'polygon',
            color: '#000000',
        },
        room: {
            type: 'polygon',
            color: '#CCCCCC',
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
    }

    // Add drawing new features
    currently_drawing = null;
    currently_adding = null;
    function add_edit_button(map, container, type, icon, callback) {
        $('<a href="#">').appendTo(container).text(icon).attr({
            href: '#',
            title: 'add '+name,
            name: type
        }).on('click', function(e) {
            e.preventDefault();

            // If we are currently adding a feature, don't start drawing another.
            if (currently_adding !== null) {
                return;
            }

            // If we are currently drawing a feature, don't start drawing another.
            if (currently_drawing !== null) {
                // If it is a feature of the same type, cancel it.
                if (currently_drawing === type) {
                    $('.leaflet-editbar .current').removeClass('current');
                    currently_drawing = null;
                    map.editTools.stopDrawing();
                }
                return;
            }

            currently_drawing = type;
            console.log(type);
            $('.leaflet-editbar .current').removeClass('current');
            $('.leaflet-editbar [name='+type+']').addClass('current');
            options = feature_types[type];
            if (options.type == 'polygon') {
                map.editTools.startPolygon(null, options);
            } else if (options.type == 'polyline') {
                map.editTools.startPolyline(null, options);
            }
        });

    }
    L.DrawControl = L.Control.extend({
        options: {
            position: 'topleft'
        },
        onAdd: function (map) {
            var container = L.DomUtil.create('div', 'leaflet-control leaflet-bar leaflet-editbar');
            add_edit_button(map, container, 'building', '🏠');
            add_edit_button(map, container, 'room', '⬠');
            add_edit_button(map, container, 'obstacle', '⬟');
            add_edit_button(map, container, 'door', '🚪');
            add_edit_button(map, container, 'step', '┌┘');
            add_edit_button(map, container, 'elevator', '▴▾');
            return container;
        }
    });
    map.addControl(new L.DrawControl());
    map.on('editable:drawing:commit', function (e) {
        currently_drawing = null;
        currently_adding = e.layer;
        $('.leaflet-editbar .current').removeClass('current');
        e.layer.disableEdit();
        L.popup({
            closeButton: false,
            autoClose: false,
        }).setContent('<img src="/static/img/loader.gif">').setLatLng(e.layer.getCenter()).openOn(map);
        console.log(e.layer.toGeoJSON());
    }).on('editable:drawing:cancel', function (e) {
        if (currently_drawing === null && currently_adding === null) {
            e.layer.remove();
        }
    });

    L.control.scale({imperial: false}).addTo(map);
}
