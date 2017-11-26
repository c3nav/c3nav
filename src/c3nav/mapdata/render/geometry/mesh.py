from collections import namedtuple

import numpy as np


class Mesh(namedtuple('Mesh', ('top', 'sides', 'bottom'))):
    __slots__ = ()
    empty_faces = np.empty((0, 3, 3)).astype(np.int32)

    def tolist(self):
        return self.top, self.sides, self.bottom

    def __mul__(self, other):
        return Mesh(top=np.rint(self.top*other).astype(np.int32),
                    sides=np.rint(self.sides*other if other[2] != 0 else self.empty_faces),
                    bottom=np.rint(self.bottom*other).astype(np.int32))

    def __add__(self, other):
        return Mesh(np.rint(self.top+other).astype(np.int32),
                    np.rint(self.sides+other).astype(np.int32),
                    np.rint(self.bottom+other).astype(np.int32))

    def filter(self, top=True, sides=True, bottom=True):
        return Mesh(top=self.top if top else self.empty_faces,
                    sides=self.sides if sides else self.empty_faces,
                    bottom=self.bottom if bottom else self.empty_faces)
