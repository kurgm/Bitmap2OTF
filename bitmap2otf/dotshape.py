# -*- coding: utf-8 -*-

import re
from xml.etree import ElementTree


def _intorfloat(v):
    vi = int(v)
    if v == vi:
        return vi
    return v


def _vec2string(x, y, suf=""):
    if x == 0:
        return "{} v{}".format(_intorfloat(y), suf)
    if y == 0:
        return "{} h{}".format(_intorfloat(x), suf)
    return "{} {} r{}".format(_intorfloat(x), _intorfloat(y), suf)


def _evalxy(xystr, x=1.0, y=1.0):
    if xystr[-1] == "x":
        return float(xystr[:-1]) * x
    if xystr[-1] == "y":
        return float(xystr[:-1]) * y
    return float(xystr)


class DotShape(object):
    def getGlyphBBX(self, bitmap, dw=100.0, dh=100.0):
        bBBX = bitmap.getBoundingBox()
        dBBX = self.getDotBBX(dw, dh)
        return [
            bBBX[0] * dw + dBBX[0],
            bBBX[1] * dh + dBBX[1],
            bBBX[2] * dw + dBBX[2],
            bBBX[3] * dh + dBBX[3]
        ]


class DotShapePixelOutline(DotShape):
    def bitmap2charstring(self, bitmap, dw=100.0, dh=100.0, subrs=[]):
        polygons = bitmap.toPolygons()
        if not polygons:
            return ""

        buf = ""
        x = y = 0.0
        for polygon in polygons:
            x1, y1 = polygon[0]
            buf += _vec2string((x1 - x) * dw, (y1 - y) * dh, "moveto ")
            x, y = x1, y1

            if polygon[0][0] == polygon[1][0]:
                currentDirection = 0
            elif polygon[0][1] == polygon[1][1]:
                currentDirection = 1
            else:
                assert False

            ops = ["hlineto ", "vlineto "]
            op = ops[1 - currentDirection]
            args = 0

            for (x1, y1), (x, y) in zip(polygon[:-1], polygon[1:]):
                distance = ((x - x1) * dw, (y - y1) * dh)
                assert distance[currentDirection] == 0.0
                currentDirection = 1 - currentDirection
                buf += "{} ".format(_intorfloat(distance[currentDirection]))

                args += 1
                # Type 2 charstring interpreter's argument stack has limit of 48
                if args == 48:
                    buf += op
                    op = ops[1 - currentDirection]
                    args = 0

            if args == 0:
                pass
            else:
                buf += op

        return buf.strip()

    def getSubroutines(self, dw=100.0, dh=100.0):
        return []

    def getDotBBX(self, dw=100.0, dh=100.0):
        return [0.0, 0.0, dw, dh]


_FACTOR_XORY_RE = re.compile(r"^[+-]?[\d.]+(?:e[+-]?\d+)?[xy]$")


class DotShapeExternal(DotShape):
    def __init__(self, src, sx=1.0, sy=1.0):
        shape = ElementTree.parse(src).getroot()
        startX = shape.get("startX", "0x")
        startY = shape.get("startY", "0y")
        self.startX = startX
        self.startY = startY
        self.endX = shape.get("endX", startX)
        self.endY = shape.get("endY", startY)
        self.charstring = shape.text
        self.sx = sx
        self.sy = sy
        self.bbx = [
            shape.get("minX", "0x"),
            shape.get("minY", "0y"),
            shape.get("maxX", "1x"),
            shape.get("maxY", "1y")
        ]

    def bitmap2charstring(self, bitmap, dw=100.0, dh=100.0, subrs=[]):
        dots = list(bitmap.dotiter())
        if not dots:
            return ""

        sx = self.sx
        sy = self.sy
        sw = sx * dw
        sh = sy * dh
        startX = _evalxy(self.startX, x=sw, y=sh)
        startY = _evalxy(self.startY, x=sw, y=sh)
        endX = _evalxy(self.endX,   x=sw, y=sh)
        endY = _evalxy(self.endY,   x=sw, y=sh)

        subrno = subrs[0]
        e2sX = startX - endX
        e2sY = startY - endY

        buf = ""

        buf += _vec2string(dots[0][0] * dw + startX,
                           dots[0][1] * dh + startY, "moveto ")
        buf += "{} callsubr ".format(subrno)

        for (x0, y0), (x1, y1) in zip(dots[:-1], dots[1:]):
            buf += _vec2string((x1 - x0) * dw + e2sX,
                               (y1 - y0) * dh + e2sY, "moveto ")
            buf += "{} callsubr ".format(subrno)

        return buf.strip()

    def getSubroutines(self, dw=100.0, dh=100.0):
        sw = self.sx * dw
        sh = self.sy * dh

        buf = []
        for token in self.charstring.split():
            if _FACTOR_XORY_RE.match(token):
                buf.append(str(_evalxy(token, x=sw, y=sh)))
            else:
                buf.append(token)

        return [" ".join(buf)]

    def getDotBBX(self, dw=100.0, dh=100.0):
        sw = self.sx * dw
        sh = self.sy * dh
        return [_evalxy(v, x=sw, y=sh) for v in self.bbx]
