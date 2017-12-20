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
    scanNow: function() {
        console.log('mobileclient: scanNow');
        $.getJSON('http://localhost:'+String(mobileclient.port)+'/scan', function(data) {
            mobileclient.setNearbyStations(data.data);
        }).fail(function() {
            mobileclient.scanNow();
        });
    },
    shareUrl: function(url) {
        console.log('mobileclient: sharing url: '+url);
    },
    createShortcut: function(url, title) {
        console.log('mobileclient: shortcut url: '+url+' title: '+title);
    }
};
