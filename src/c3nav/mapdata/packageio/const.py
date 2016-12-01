from c3nav.mapdata.models import Level, Package, Source
from c3nav.mapdata.models.collections import Elevator
from c3nav.mapdata.models.geometry import Building, Door, ElevatorLevel, Hole, LevelConnector, Obstacle, Outside, Room

ordered_models = (Package, Level, LevelConnector, Source, Building, Room, Outside, Door, Obstacle, Hole)
ordered_models += (Elevator, ElevatorLevel)
