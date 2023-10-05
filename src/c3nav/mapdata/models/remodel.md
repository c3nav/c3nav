# by file

## access

- AccessRestriction (TitledMixin) → Collection
- AccessRestrictionGroup (TitledMixin) → Collection
- AccessPermissionToken → Offer[Collection[AccessPermission]]
- AccessPermission
- (abstract) AccessRestrictionMixin

## base

- (abstract) SerializableMixin
- (abstract) TitledMixin (SerializableMixin)
- (abstract) BoundsMixin (SerializableMixin)

## graph

- GraphNode(SpaceGeometryMixin) → 
- WayType(SerializableMixin) →
- GraphEdge(AccessRestrictionMixin) →

## level

- Level(SpecificLocation) → Place

## locations

- LocationSlug(SerializableMixin)
- (abstract) Location(LocationSlug, AccessRestrictionMixin, TitledMixin)
- (abstract) SpecificLocation(Location)
- LocationGroupCategory(SerializableMixin)
- LocationGroup(Location) → Place
- LocationRedirect(LocationSlug)
- LabelSettings(SerializableMixin) → Place
- (abstract) CustomLocationProxyMixin
- DynamicLocation(CustomLocationProxyMixin, SpecificLocation)
- Position(CustomLocationProxyMixin)

## report
- Report
- ReportUpdate

## source
- Source(BoundsMixin, AccessRestrictionMixin)

## update
- MapUpdate

## geometry/base
- (abstract) GeometryMixin(SerializableMixin)

## geometry/level
- (abstract) LevelGeometryMixin(GeometryMixin)
- Building(LevelGeometryMixin)
- Space(LevelGeometryMixin, SpecificLocation)
- Door(LevelGeometryMixin, AccessRestrictionMixin)
- AltitudeArea(LevelGeometryMixin)

## geometry/space
- (abstract) SpaceGeometryMixin(GeometryMixin)
- Column(SpaceGeometryMixin, AccessRestrictionMixin)
- Area(SpaceGeometryMixin, SpecificLocation)
- Stair(SpaceGeometryMixin)
- Ramp(SpaceGeometryMixin)
- Obstacle(SpaceGeometryMixin)
- LineObstacle(SpaceGeometryMixin)
- POI(SpaceGeometryMixin, SpecificLocation)
- Hole(SpaceGeometryMixin)
- AltitudeMarker(SpaceGeometryMixin)
- LeaveDescription(SerializableMixin)
- CrossDescription(SerializableMixin)
- WifiMeasurement(SpaceGeometryMixin)



# by inheritance

- (abstract) base.SerializableMixin
- (abstract) base.TitledMixin (Serializable)
- (abstract) base.BoundsMixin (Serializable)
- (abstract) locations.CustomLocationProxyMixin
- (abstract) geometry.base.GeometryMixin (Serializable)
- (abstract) access.AccessRestrictionMixin
- (abstract) geometry.level.LevelGeometryMixin (Geometry)
- (abstract) geometry.space.SpaceGeometryMixin (Geometry)


- graph.GraphNode (SpaceGeometry)
- graph.WayType (Serializable)
- graph.GraphEdge (AccessRestriction)


- access.AccessRestriction (Titled)
- access.AccessRestrictionGroup (Titled)
- access.AccessPermissionToken 
- access.AccessPermission


- locations.LocationSlug (Serializable)
  - *(has a slug)*
  - locations.LocationRedirect (Serializable)
  - (abstract) locations.Location (Serializable, AccessRestriction, Titled)
    - *(can_search/can_describe/icon)*
    - locations.LocationGroup (Serializable, AccessRestriction, Titled)
    - (abstract) locations.SpecificLocation (Serializable, AccessRestriction, Titled)
      - *(groups, label_setting, label_override* 
      - locations.DynamicLocation (CustomLocationProxy)
      - level.Level
      - geometry.level.Space (LevelGeometry)
      - geometry.space.Area (SpaceGeometry)
      - geometry.space.POI (SpaceGeometry)

    
- locations.LocationGroupCategory (Serializable)
- locations.LabelSettings (Serializable)
- locations.Position (CustomLocationProxy)


- source.Source(Bounds, AccessRestriction)


- report.Report
- report.ReportUpdate
- update.MapUpdate


- geometry.level.Building (LevelGeometry)
- geometry.level.Door (LevelGeometry, AccessRestriction)
- geometry.level.AltitudeArea (LevelGeometry)


- geometry.space.Column(SpaceGeometry, AccessRestriction)
- geometry.space.Stair(SpaceGeometry)
- geometry.space.Ramp(SpaceGeometry)
- geometry.space.Obstacle(SpaceGeometry)
- geometry.space.LineObstacle(SpaceGeometry)
- geometry.space.Hole(SpaceGeometry)
- geometry.space.AltitudeMarker(SpaceGeometry)
- geometry.space.WifiMeasurement(SpaceGeometry)


- geometry.space.LeaveDescription(Serializable)
- geometry.space.CrossDescription(Serializable)