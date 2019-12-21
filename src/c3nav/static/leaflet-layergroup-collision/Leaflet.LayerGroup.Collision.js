

var isMSIE8 = !('getComputedStyle' in window && typeof window.getComputedStyle === 'function')

function extensions(parentClass) { return {

	initialize: function (arg1, arg2) {
		var options;
		if (parentClass === L.GeoJSON) {
			parentClass.prototype.initialize.call(this, arg1, arg2);
			options = arg2;
		} else {
			parentClass.prototype.initialize.call(this, arg1);
			options = arg1;
		}
		this._originalLayers = [];
		this._visibleLayers = [];
		this._staticLayers = [];
		this._rbush = [];
		this._cachedRelativeBoxes = [];
		this._margin = options.margin || 0;
		this._rbush = null;
	},

	addLayer: function(layer) {
		if ( !('options' in layer) || !('icon' in layer.options)) {
			this._staticLayers.push(layer);
			parentClass.prototype.addLayer.call(this, layer);
			return;
		}

		this._originalLayers.push(layer);
		if (this._map) {
			this._maybeAddLayerToRBush( layer );
		}
	},

	removeLayer: function(layer) {
		this._rbush.remove(this._cachedRelativeBoxes[layer._leaflet_id]);
		delete this._cachedRelativeBoxes[layer._leaflet_id];
		parentClass.prototype.removeLayer.call(this,layer);
		var i;

		i = this._originalLayers.indexOf(layer);
		if (i !== -1) { this._originalLayers.splice(i,1); }

		i = this._visibleLayers.indexOf(layer);
		if (i !== -1) { this._visibleLayers.splice(i,1); }

		i = this._staticLayers.indexOf(layer);
		if (i !== -1) { this._staticLayers.splice(i,1); }
	},

	clearLayers: function() {
		this._rbush = rbush();
		this._originalLayers = [];
		this._visibleLayers  = [];
		this._staticLayers   = [];
		this._cachedRelativeBoxes = [];
		parentClass.prototype.clearLayers.call(this);
	},

	onAdd: function (map) {
		this._map = map;

		for (var i in this._staticLayers) {
			map.addLayer(this._staticLayers[i]);
		}

		this._onZoomEnd();
		map.on('zoomend', this._onZoomEnd, this);
	},

	onRemove: function(map) {
		for (var i in this._staticLayers) {
			map.removeLayer(this._staticLayers[i]);
		}
		map.off('zoomend', this._onZoomEnd, this);
		parentClass.prototype.onRemove.call(this, map);
	},

	_maybeAddLayerToRBush: function(layer) {

		var z    = this._map.getZoom();
		var bush = this._rbush;

		var boxes = this._cachedRelativeBoxes[layer._leaflet_id];
		var visible = false;
		if (!boxes) {
			// Add the layer to the map so it's instantiated on the DOM,
			//   in order to fetch its position and size.
			parentClass.prototype.addLayer.call(this, layer);
			var visible = true;
// 			var htmlElement = layer._icon;
			var box = this._getIconBox(layer._icon);
			boxes = this._getRelativeBoxes(layer._icon.children, box);
			boxes.push(box);
			this._cachedRelativeBoxes[layer._leaflet_id] = boxes;
		}

		boxes = this._positionBoxes(this._map.latLngToLayerPoint(layer.getLatLng()),boxes);

		var collision = false;
		for (var i=0; i<boxes.length && !collision; i++) {
			collision = bush.search(boxes[i]).length > 0;
		}

		if (!collision) {
			if (!visible) {
				parentClass.prototype.addLayer.call(this, layer);
			}
			this._visibleLayers.push(layer);
			bush.load(boxes);
		} else {
			parentClass.prototype.removeLayer.call(this, layer);
		}
	},


	// Returns a plain array with the relative dimensions of a L.Icon, based
	//   on the computed values from iconSize and iconAnchor.
	_getIconBox: function (el) {

		if (isMSIE8) {
			// Fallback for MSIE8, will most probably fail on edge cases
			return [ 0, 0, el.offsetWidth, el.offsetHeight];
		}

		var styles = window.getComputedStyle(el);

		// getComputedStyle() should return values already in pixels, so using parseInt()
		//   is not as much as a hack as it seems to be.

		return [
			parseInt(styles.marginLeft),
			parseInt(styles.marginTop),
			parseInt(styles.marginLeft) + parseInt(styles.width),
			parseInt(styles.marginTop)  + parseInt(styles.height)
		];
	},


	// Much like _getIconBox, but works for positioned HTML elements, based on offsetWidth/offsetHeight.
	_getRelativeBoxes: function(els,baseBox) {
		var boxes = [];
		for (var i=0; i<els.length; i++) {
			var el = els[i];
			var box = [
				el.offsetLeft,
				el.offsetTop,
				el.offsetLeft + el.offsetWidth,
				el.offsetTop  + el.offsetHeight
			];
			box = this._offsetBoxes(box, baseBox);
			boxes.push( box );

			if (el.children.length) {
				var parentBox = baseBox;
				if (!isMSIE8) {
					var positionStyle = window.getComputedStyle(el).position;
					if (positionStyle === 'absolute' || positionStyle === 'relative') {
						parentBox = box;
					}
				}
				boxes = boxes.concat( this._getRelativeBoxes(el.children, parentBox) );
			}
		}
		return boxes;
	},

	_offsetBoxes: function(a,b){
		return [
			a[0] + b[0],
			a[1] + b[1],
			a[2] + b[0],
			a[3] + b[1]
		];
	},

	// Adds the coordinate of the layer (in pixels / map canvas units) to each box coordinate.
	_positionBoxes: function(offset, boxes) {
		var newBoxes = [];	// Must be careful to not overwrite references to the original ones.
		for (var i=0; i<boxes.length; i++) {
			newBoxes.push( this._positionBox( offset, boxes[i] ) );
		}
		return newBoxes;
	},

	_positionBox: function(offset, box) {

		return [
			box[0] + offset.x - this._margin,
			box[1] + offset.y - this._margin,
			box[2] + offset.x + this._margin,
			box[3] + offset.y + this._margin,
		]
	},

	_onZoomEnd: function() {

		for (var i=0; i<this._visibleLayers.length; i++) {
			parentClass.prototype.removeLayer.call(this, this._visibleLayers[i]);
		}

		this._rbush = rbush();

		for (var i=0; i < this._originalLayers.length; i++) {
			this._maybeAddLayerToRBush(this._originalLayers[i]);
		}

	}
}};


L.LayerGroup.Collision   = L.LayerGroup.extend(extensions( L.LayerGroup ));
L.FeatureGroup.Collision = L.FeatureGroup.extend(extensions( L.FeatureGroup ));
L.GeoJSON.Collision      = L.GeoJSON.extend(extensions( L.GeoJSON ));

// Uppercase factories only for backwards compatibility:
L.LayerGroup.collision = function (options) {
	return new L.LayerGroup.Collision(options || {});
};

L.FeatureGroup.collision = function (options) {
	return new L.FeatureGroup.Collision(options || {});
};

L.GeoJSON.collision = function (geojson, options) {
	return new L.GeoJSON.Collision(geojson, options || {});
};

// Factories should always be lowercase, like this:
L.layerGroup.collision = function (options) {
	return new L.LayerGroup.Collision(options || {});
};

L.featureGroup.collision = function (options) {
	return new L.FeatureGroup.Collision(options || {});
};

L.geoJson.collision = function (geojson, options) {
	return new L.GeoJSON.Collision(geojson, options || {});
};

