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
    shareUrl: function(url) {
        console.log('mobileclient: sharing url: '+url);
    },
    createShortcut: function(url, title) {
        console.log('mobileclient: shortcut url: '+url+' title: '+title);
    }
};
