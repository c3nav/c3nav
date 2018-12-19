mobileclient = {
    nearbyStations: [],
    setNearbyStations: function(data) {
        this.nearbyStations = data;
        nearby_stations_available();
    },
    getNearbyStations: function() {
        return JSON.stringify(this.nearbyStations);
    },
    port: 8042,
    wait: false,
    scanNow: function() {
        console.log('mobileclient: scanNow');
        if (mobileclient.wait) return;
        mobileclient.wait = true;
        $.getJSON('http://localhost:'+String(mobileclient.port)+'/scan', function(data) {
            mobileclient.setNearbyStations(data.data);
        }).always(function() {
            mobileclient.wait = false;
        });
    },
    _locationPermission: false,
    hasLocationPermission: function() {
        console.log('mobileclient hasLocationPermission: ' + window.mobileclient._locationPermission);
        return window.mobileclient._locationPermission;
    },
    checkLocationPermission: function(requestPermission) {
        requestPermission = requestPermission ? true : false;
        console.log('mobileclient checkLocationPermission(' + requestPermission + ')');
        window.mobileclient._locationPermission = true;
        return true
    },
    shareUrl: function(url) {
        console.log('mobileclient: sharing url: '+url);
    },
    createShortcut: function(url, title) {
        console.log('mobileclient: shortcut url: '+url+' title: '+title);
    },
    setUserData: function(user_data) {
        console.log('setUserData');
        console.log(JSON.parse(user_data));
    },
};
