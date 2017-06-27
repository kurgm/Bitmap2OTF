# -*- coding: utf-8 -*-

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

from functools import reduce
import sys

PY2 = sys.version_info < (3, 0)

if PY2:
    pass
else:
    unichr = chr

    def chr(x):
        return unichr(x).encode("latin-1")


def _makebold_row_type0(row, align=False):
    row0 = row + [0]
    row1 = [0] + row
    return [b0 or b1 for b0, b1 in zip(row0, row1)]


def _makebold_row_type1(row, alignRight=False):
    if alignRight:
        row0 = [0] + row
        row1 = row + [0]
        row2 = row[1:] + [0, 0]
    else:
        row0 = row + [0]
        row1 = [0] + row
        row2 = [0, 0] + row[:-1]

    return [b1 or (b0 and not b2) for b0, b1, b2 in zip(row0, row1, row2)]


_makebold_row = {
    0: _makebold_row_type0,
    1: _makebold_row_type1
}

#    U
#   2|3
# L -+- R
#   0|1
#    D
_D = 0
_L = 1
_R = 2
_U = 3

_polygons_bit2edgedirs = {
    (False, False, False, False): (),
    (False, False, False, True): ((_U, _R), ),
    (False, False, True, False): ((_L, _U), ),
    (False, False, True, True): (),
    (False, True, False, False): ((_R, _D), ),
    (False, True, False, True): (),
    (False, True, True, False): ((_R, _D), (_L, _U)),
    (False, True, True, True): ((_L, _D), ),
    (True, False, False, False): ((_D, _L), ),
    (True, False, False, True): ((_D, _L), (_U, _R)),
    (True, False, True, False): (),
    (True, False, True, True): ((_D, _R), ),
    (True, True, False, False): (),
    (True, True, False, True): ((_U, _L), ),
    (True, True, True, False): ((_R, _U), ),
    (True, True, True, True): ()
}


def _binary2imagedata(bitarray):
    data = b""
    for i in range(0, len(bitarray), 8):
        byteArray = bitarray[i:i + 8]
        if len(byteArray) < 8:
            byteArray += [False] * (8 - len(byteArray))
        byte = 0
        for i in range(8):
            byte <<= 1
            if byteArray[i]:
                byte |= 1
        data += chr(byte)

    return data


class Bitmap(object):
    """Bitmap with metrics. Bottom-to-top and left-to-right."""

    def __init__(self, bitmap=[[]], origin=(0, 0), advance=None, voriginy=0):
        self.bitmap = [row[:] for row in bitmap]  # copy
        self.height = len(bitmap)
        self.width = len(bitmap[0])
        self.origin = origin
        if advance is None:
            advance = (self.width, self.height)
        self.advanceWidth, self.advanceHeight = advance
        self.voriginy = voriginy
        for r in bitmap:
            assert len(r) == self.width

    def makebold(self, boldtype=0, x=1, y=0, x2=0, y2=0):
        for i in range(x):
            self._makebold_x(boldtype, i < x2)

        self.bitmap = [list(row) for row in zip(*self.bitmap)]

        for i in range(y):
            self._makebold_x(boldtype, i < y2)

        self.bitmap = [list(row) for row in zip(*self.bitmap)]

        self.width += x
        self.height += y
        self.advanceWidth += x
        self.advanceHeight += y
        self.voriginy += y

    def _makebold_x(self, boldtype=0, align=False):
        self.bitmap = [_makebold_row[boldtype](
            row, align) for row in self.bitmap]

    def makeitalic(self, cotangent):
        if cotangent == 0:
            return

        slanttoleft = cotangent < 0
        abscotangent = abs(cotangent)

        y = 0
        while y < self.height:
            for i in range(self.height):
                if (i < y) ^ slanttoleft:
                    self.bitmap[i].append(0)
                else:
                    self.bitmap[i].insert(0, 0)
            y += abscotangent

        ox, oy = self.origin
        ox += oy / float(cotangent)

        self.width = len(self.bitmap[0])
        self.origin = (ox, oy)

    def translate(self, x=0, y=0):
        ox, oy = self.origin
        self.origin = (ox - x, oy - y)

    def rotate(self, n=1):
        assert isinstance(n, int)

        n %= 4

        if n == 0:
            return
        if n == 2:
            self.bitmap.reverse()
            for r in self.bitmap:
                r.reverse()
            self.origin = (
                self.width - self.origin[0], self.height - self.origin[1])
            return

        if n == 1:
            self.bitmap = [list(row) for row in zip(*self.bitmap)]
            self.bitmap.reverse()
            self.origin = (self.origin[1], self.width - self.origin[0])
        if n == 3:
            self.bitmap.reverse()
            self.bitmap = [list(row) for row in zip(*self.bitmap)]
            self.origin = (self.height - self.origin[1], self.origin[0])

        self.width, self.height = self.height, self.width
        self.advanceWidth, self.advanceHeight = self.advanceHeight, self.advanceWidth

    def scale(self, x=1, y=1):
        assert x >= 0 and y >= 0

        self._scaley(y)

        self.bitmap = [list(row) for row in zip(*self.bitmap)]
        self.width, self.height = self.height, self.width
        self._scaley(x)
        self.bitmap = [list(row) for row in zip(*self.bitmap)]
        self.width, self.height = self.height, self.width

        self.advanceWidth *= x
        self.advanceHeight *= y
        self.voriginy *= y
        self.origin = (self.origin[0] * x, self.origin[1] * y)

    def _scaley(self, sy):
        if sy == 1:
            return

        newbmp = []

        for y in range(len(self.bitmap)):
            for i in range(len(newbmp), int((y + 1) * sy)):
                newbmp.append(list(self.bitmap[y]))

        self.bitmap = newbmp
        self.height = len(newbmp)

    def dotiter(self):
        for y in range(self.height):
            for x in range(self.width):
                if self.bitmap[y][x]:
                    yield (x - self.origin[0], y - self.origin[1])

    def getBoundingBox(self):
        INFINITY = float("inf")
        minX = +INFINITY
        minY = +INFINITY
        maxX = -INFINITY
        maxY = -INFINITY
        for x, y in self.dotiter():
            minX = min(minX, x)
            minY = min(minY, y)
            maxX = max(maxX, x)
            maxY = max(maxY, y)

        if minX == +INFINITY:
            return (0, 0, 0, 0)

        return (minX, minY, maxX, maxY)

    def getPixel(self, x, y):
        x += self.origin[0]
        y += self.origin[1]
        if not (0 <= x < self.width and 0 <= y < self.height):
            return False
        return self.bitmap[int(round(y))][int(round(x))]

    def getPixel2(self, x, y):
        if not (0 <= x < self.width and 0 <= y < self.height):
            return False
        return self.bitmap[y][x]

    def toPolygons(self):
        vertices = []

        for y in range(self.height + 1):
            for x in range(self.width + 1):
                b0 = bool(self.getPixel2(x - 1, y - 1))
                b1 = bool(self.getPixel2(x, y - 1))
                b2 = bool(self.getPixel2(x - 1, y))
                b3 = bool(self.getPixel2(x, y))
                edgedirs = _polygons_bit2edgedirs[(b0, b1, b2, b3)]
                vertices.extend([[x - self.origin[0], y - self.origin[1],
                                  dir_in, dir_out] for dir_in, dir_out in edgedirs])

        vertices_by_dir_in = {
            _D: [],
            _L: [],
            _R: [],
            _U: []
        }
        for v in vertices:
            vertices_by_dir_in[v[2]].append(v)

        polygons = []
        while vertices:
            polygon = []
            v0 = vertices[0]
            v = v0
            while True:
                polygon.append(v[0:2])

                next_dir_in = 3 - v[3]
                if next_dir_in == _D:
                    v1 = sorted(
                        [vn for vn in vertices_by_dir_in[next_dir_in]
                            if vn[0] == v[0] and vn[1] > v[1]],
                        key=lambda vn: vn[1] - v[1])[0]
                elif next_dir_in == _U:
                    v1 = sorted(
                        [vn for vn in vertices_by_dir_in[next_dir_in]
                            if vn[0] == v[0] and vn[1] < v[1]],
                        key=lambda vn: v[1] - vn[1])[0]
                elif next_dir_in == _L:
                    v1 = sorted(
                        [vn for vn in vertices_by_dir_in[next_dir_in]
                            if vn[1] == v[1] and vn[0] > v[0]],
                        key=lambda vn: vn[0] - v[0])[0]
                elif next_dir_in == _R:
                    v1 = sorted(
                        [vn for vn in vertices_by_dir_in[next_dir_in]
                            if vn[1] == v[1] and vn[0] < v[0]],
                        key=lambda vn: v[0] - vn[0])[0]
                vertices.remove(v1)
                vertices_by_dir_in[v1[2]].remove(v1)
                if v1 is v0:
                    break
                v = v1
            polygons.append(polygon)

        return polygons

    def getImageDataSize(self):
        bits = self.width * self.height
        return (bits + 7) // 8

    def toImageData(self):
        buf = reduce(lambda a, b: a + b, reversed(self.bitmap), [])
        return _binary2imagedata(buf)

    def hasSameMetrics(self, other):
        return all(getattr(self, key) == getattr(other, key) for key in ("width", "height", "origin", "advanceWidth", "advanceHeight", "voriginy"))

    def __str__(self):
        return "O({0[0]},{0[1]}), aw={1}, ah={2}, vo={3}\n".format(self.origin, self.advanceWidth, self.advanceHeight, self.voriginy) + "\n".join("".join("@" if c else "." for c in r) for r in reversed(self.bitmap))
