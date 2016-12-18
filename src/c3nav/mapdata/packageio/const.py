from c3nav.mapdata.models import AreaLocation, Level, LocationGroup, Package, Source
from c3nav.mapdata.models.collections import Elevator
from c3nav.mapdata.models.geometry import (Building, Door, ElevatorLevel, Escalator, EscalatorSlope, Hole,
                                           LevelConnector, LineObstacle, Obstacle, Outside, Room, Stair)

ordered_models = (Package, Level, LevelConnector, Source, Building, Room, Outside, Door, Obstacle, Hole)
ordered_models += (Elevator, ElevatorLevel, LineObstacle, Stair, Escalator, EscalatorSlope)
ordered_models += (LocationGroup, AreaLocation)
