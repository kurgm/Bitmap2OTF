# -*- coding: utf-8 -*-

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import logging
import os.path
import re
from xml.etree import ElementTree

from fontTools.misc.textTools import safeEval
from PIL import Image

from bitmapfont import BitmapFont
from bitmapfont import BitmapGlyph
from dotshape import DotShapeExternal
from dotshape import DotShapePixelOutline

log = logging.getLogger(__name__)


def _myord(c):
    buf = []
    i = 0
    l = len(c)
    while i < l:
        oc0 = ord(c[i])
        i += 1
        if i < l and 0xD800 <= oc0 < 0xDC00:
            oc1 = ord(c[i])
            i += 1
            buf.append(0x10000 + ((oc0 & 0x3FF) << 10) | (oc1 & 0x3FF))
        else:
            buf.append(oc0)
    return buf


class ConfigFileError(Exception):
    pass


def _findChildOrError(elem, path, attribute=None):
    c = elem.find("./" + path)
    if c is None:
        raise ConfigFileError(
            "element '{}' not found under element '{}'".format(path, elem.tag))
    if attribute is not None:
        return _findAttrOrError(c, attribute)
    return c


def _findAttrOrError(elem, attribute):
    v = elem.get(attribute)
    if v is None:
        raise ConfigFileError(
            "element '{}' has no attribute '{}'".format(elem.tag, attribute))
    return v


def _getGlyphOptions(elem, default=[], basepath=""):
    items = elem.items()
    res = list(default)
    for key, val in items:
        if key in ("fromChar", "fromCodepoint", "fromName") and elem.tag == "Copy":
            continue
        if key in ("stepx", "stepy", "charsPerRow") and elem.tag in ("Image", "Glyphs"):
            continue

        if key in ("x", "y") and elem.tag in ("Image", "Glyph", "Glyphs"):
            val = safeEval(val)
        elif key in ("codepoint", "advancewidth", "advanceheight", "bitmapwidth", "bitmapheight", "originx", "originy", "voriginy"):
            val = safeEval(val)
        elif key == "src" and elem.tag == "Image":
            val = os.path.join(basepath, val)
        elif key == "name":
            pass
        elif key == "char":
            res.append(("codepoint", _myord(val)[0]))
            continue
        else:
            raise ConfigFileError(
                "element '{}' has unknown glyph attribute '{}'".format(elem.tag, key))
        res.append((key, val))
    return res


def _isVariationSelector(code):
    isVS = 0xFE00 <= code <= 0xFE0F or 0xE0100 <= code <= 0xE01EF
    if isVS:
        log.warn("variation selectors are not supported for now.")
    return isVS


def _myord_filterTabAndNewlines(s):
    # \t, \r, \n
    return [c for c in _myord(s) if c not in (9, 10, 13) and not _isVariationSelector(c)]


def _getCodepointList(elem):
    return _myord_filterTabAndNewlines(elem.text or "")


def _getNameOrCodepointList(elem, allowAllGlyphs=False):
    res = []
    res.extend(("codepoint", c) for c in _getCodepointList(elem))
    for subelem in elem:
        if allowAllGlyphs and subelem.tag == "AllGlyphs":
            res.append(("allglyphs", None))
            continue
        if subelem.tag != "Glyph":
            raise ConfigFileError(
                "unknown element '{}' found in element '{}'".format(subelem.tag, elem.tag))
        if subelem.get("name") is not None:
            res.append(("name", subelem.get("name")))
        elif subelem.get("codepoint") is not None:
            res.append(("codepoint", safeEval(subelem.get("codepoint"))))
        elif subelem.get("char") is not None:
            res.append(("codepoint", _myord(subelem.get("char"))[0]))
        else:
            log.warn(
                "ignoring Glyph element which has none of attributes 'name', 'codepoint' and 'char'.")
        res.extend(("codepoint", c)
                   for c in _myord_filterTabAndNewlines(subelem.tail))
    return res


_nameKeyword2nameID = {
    "copyright": 0,
    "fontfamily": 1,
    "subfamily": 2,
    "uniqueid": 3,
    "fullname": 4,
    "version": 5,
    "postscriptname": 6,
    "trademark": 7,
    "manufacturer": 8,
    "designer": 9,
    "description": 10,
    "urlvendor": 11,
    "urldesigner": 12,
    "license": 13,
    "licenseurl": 14,
    # reserved: 15
    "typographicfamily": 16,
    "typographicsubfamily": 17,
    "compatiblefull": 18,
    "sampletext": 19,
    "cidName": 20,
    "wwsfamily": 21,
    "wwssubfamily": 22,

    # aliases
    "preferredfamily": 16,
    "preferredsubfamily": 17
}


class NameRecord(object):
    def __init__(self, platformID, platEncID, langID, records=None):
        if records is None:
            records = {}
        self.platformID = platformID
        self.platEncID = platEncID
        self.langID = langID
        self.records = records


class FontInfo(object):
    def __init__(self):
        self.settings = {
            "ascent": 0,
            "descent": 0,
            "x-height": 0,
            "vertascent": 0,
            "vertdescent": 0,
            "bold": 0,
            "italic": 0
        }
        self.names = []
        self.cffNames = None

    def fromXML(self, elem):
        if elem.tag == "setting":
            key = _findAttrOrError(elem, "key")
            val = _findAttrOrError(elem, "value")
            if key in ("ascent", "descent", "x-height", "vertascent", "vertdescent", "bold", "italic"):
                val = safeEval(val)
            else:
                log.warn(
                    "ignoring unknown parameter '{}' in FontInfo.".format(key))
                return
            self.settings[key] = val
        elif elem.tag == "namerecords":
            platformID = safeEval(_findAttrOrError(elem, "platformID"))
            platEncID = safeEval(_findAttrOrError(elem, "platEncID"))
            langID = safeEval(_findAttrOrError(elem, "langID"))

            try:
                list(platformID)
            except TypeError:
                platformID = (platformID, )
                platEncID = (platEncID, )
                langID = (langID, )

            if not (len(platformID) == len(platEncID) == len(langID)):
                raise ConfigFileError(
                    "each of platformID, platEncID and langID must have the same number of values")

            records = {}
            for r in elem:
                if r.get("nameID") is not None:
                    nameID = safeEval(r.get("nameID"))
                else:
                    keyword = _findAttrOrError(r, "key")
                    nameID = _nameKeyword2nameID.get(keyword.lower())
                    if nameID is None:
                        log.warn(
                            "ignoring unknown keyword '{}' in namerecord.".format(keyword))
                        continue
                records[nameID] = _findAttrOrError(r, "value")

            self.names.append(NameRecord(
                platformID, platEncID, langID, records))

            if safeEval(elem.get("useAsCFFNames", "False")):
                self.cffNames = records
        else:
            log.warn("ignoring unknown element '{}' in FontInfo.".format(elem.tag))

    def getCFFNames(self):
        if self.cffNames is not None:
            return self.cffNames

        for namerecord in self.names:
            for ids in zip(namerecord.platformID, namerecord.platEncID, namerecord.langID):
                if ids in ((1, 0, 0), (3, 1, 0x409)):
                    self.cffNames = namerecord.records
                    break
        else:
            raise ConfigFileError(
                "namerecords to use as CFF names were not found")

        if _nameKeyword2nameID["postscriptname"] not in self.cffNames:
            raise ConfigFileError(
                "'postscriptName' record was not found in the namerecords to use as CFF names")

        return self.cffNames


class Config(object):
    def __init__(self, configfilepath):
        configdirpath = os.path.dirname(configfilepath)

        root = ElementTree.parse(configfilepath)
        self.templateTTXpath = os.path.join(
            configdirpath, _findChildOrError(root, "TemplateTTX", "src"))

        self.outputTo = os.path.splitext(configfilepath)[0] + ".otf"
        outputTo = root.find("./Output")
        if outputTo is not None:
            self.outputTo = os.path.join(
                configdirpath, outputTo.get("path", self.outputTo))

        fontinfo = _findChildOrError(root, "FontInfo")
        self.fontinfo = FontInfo()
        for elem in fontinfo:
            self.fontinfo.fromXML(elem)

        outline = _findChildOrError(root, "Outline")
        self.outlineCfg = {
            "dotsize_x": 100,
            "dotsize_y": 100,
            "shapetype": "pixel-outline",
            "shapesrc": None,
            "shapesize_x": 1.0,
            "shapesize_y": 1.0
        }

        dotsize = outline.find("./DotSize")
        if dotsize is not None:
            self.outlineCfg["dotsize_x"] = safeEval(dotsize.get("x", "100"))
            self.outlineCfg["dotsize_y"] = safeEval(dotsize.get("y", "100"))

        dotshape = outline.find("./DotShape")
        if dotshape is not None:
            shapetype = dotshape.get("type")
            if shapetype is not None:
                if shapetype != "pixel-outline":
                    raise ConfigFileError(
                        "unknown dot shape type '{}'".format(shapetype))
                self.outlineCfg["shapetype"] = shapetype
            else:
                shapesrc = dotshape.get("src")
                if shapesrc is None:
                    raise ConfigFileError(
                        "Either attribute 'type' or 'src' is required for 'DotShape' element")
                self.outlineCfg["shapetype"] = None
                self.outlineCfg["shapesrc"] = os.path.join(
                    configdirpath, shapesrc)
                self.outlineCfg["shapescale_x"] = float(
                    dotshape.get("width", "1.0"))
                self.outlineCfg["shapescale_y"] = float(
                    dotshape.get("height", "1.0"))

        bitmap = root.find("./Bitmap")
        self.generateBitmap = bitmap is not None

        glyphsrcs = _findChildOrError(root, "GlyphSources")
        self.glyphsources = []

        default_settings = _getGlyphOptions(glyphsrcs, basepath=configdirpath)
        for glyphsrc in glyphsrcs:
            glyphsrc_settings = _getGlyphOptions(
                glyphsrc, default_settings, basepath=configdirpath)
            if glyphsrc.tag == "BitmapData":
                glyph = GlyphSourceBitmap(
                    glyphsrc.text, **dict(glyphsrc_settings))
                self.glyphsources.append(glyph)
            elif glyphsrc.tag == "Space":
                glyph = GlyphSourceSpace(**dict(glyphsrc_settings))
                self.glyphsources.append(glyph)
            elif glyphsrc.tag == "Spaces":
                chars = _getCodepointList(glyphsrc)
                for char in chars:
                    glyph = GlyphSourceSpace(
                        **dict(glyphsrc_settings + [("codepoint", char)]))
                    self.glyphsources.append(glyph)
            elif glyphsrc.tag == "Image":
                image_stepx = glyphsrc.get("stepx", "None")
                image_stepy = glyphsrc.get("stepy", "None")
                image_charsperrow = glyphsrc.get("charsPerRow")
                for glypharea in glyphsrc:
                    glypharea_settings = _getGlyphOptions(
                        glypharea, glyphsrc_settings, basepath=configdirpath)
                    if glypharea.tag == "Glyph":
                        glyph = GlyphSourceImage(**dict(glypharea_settings))
                        self.glyphsources.append(glyph)
                    elif glypharea.tag == "Glyphs":
                        d = dict(glypharea_settings)
                        x = d["x"]
                        y = d["y"]
                        stepx = safeEval(glypharea.get("stepx", image_stepx))
                        stepy = safeEval(glypharea.get("stepy", image_stepy))
                        charsperrow = safeEval(glypharea.get(
                            "charsPerRow", image_charsperrow))
                        if stepx is None or stepy is None or charsperrow is None:
                            raise ConfigFileError(
                                "all of stepx, stepy and charsPerRow attributes must be specified in either Image or Glyphs element")
                        glyphopts = _getNameOrCodepointList(glypharea)
                        x0 = x
                        for i, glyphopt in enumerate(glyphopts):
                            glyph = GlyphSourceImage(**dict(glypharea_settings + [
                                ("x", x), ("y", y),
                                glyphopt
                            ]))
                            self.glyphsources.append(glyph)
                            if (i + 1) % charsperrow == 0:
                                x = x0
                                y += stepy
                            else:
                                x += stepx
                    else:
                        raise ConfigFileError(
                            "unknown element '{}' in Image element".format(glypharea.tag))
            elif glyphsrc.tag == "Copy":
                if glyphsrc.get("fromChar") is not None:
                    glyphopt = ("srccodepoint", _myord(
                        glyphsrc.get("fromChar"))[0])
                elif glyphsrc.get("fromCodepoint") is not None:
                    glyphopt = ("srccodepoint", safeEval(
                        glyphsrc.get("fromCodepoint")))
                elif glyphsrc.get("fromName") is not None:
                    glyphopt = ("srcname", glyphsrc.get("fromName"))
                else:
                    raise ConfigFileError(
                        "fromChar, fromCodepoint or fromName attribute is required for 'Copy' element")
                glyph = GlyphSourceGlyph(
                    **dict(glyphsrc_settings + [glyphopt]))
                self.glyphsources.append(glyph)
            else:
                log.warn("ignoring unknown glyph source '{}'.".format(
                    glyphsrc.tag))
        self.effects = []
        effects = root.find("./Effects")
        if effects is not None:
            for effect in effects:
                glyphopts = _getNameOrCodepointList(
                    effect, allowAllGlyphs=True)
                if effect.tag == "makebold":
                    self.effects.append([glyphopts, "makebold", [
                        safeEval(effect.get("boldtype", "0")),
                        safeEval(effect.get("x", "1")),
                        safeEval(effect.get("y", "0")),
                        safeEval(effect.get("x2", "0")),
                        safeEval(effect.get("y2", "0"))
                    ]])
                elif effect.tag == "makeitalic":
                    self.effects.append([glyphopts, "makeitalic", [
                        safeEval(_findAttrOrError(effect, "cotangent")),
                    ]])
                elif effect.tag == "translate":
                    self.effects.append([glyphopts, "translate", [
                        safeEval(effect.get("x", "0")),
                        safeEval(effect.get("y", "0"))
                    ]])
                elif effect.tag == "rotate":
                    self.effects.append([glyphopts, "rotate", [
                        safeEval(effect.get("n", "1"))
                    ]])
                elif effect.tag == "scale":
                    self.effects.append([glyphopts, "scale", [
                        safeEval(effect.get("x", "1")),
                        safeEval(effect.get("y", "1"))
                    ]])
                else:
                    log.warn("ignoring unknown effect '{}'".format(effect.tag))

        self.templateTTX2 = [os.path.join(configdirpath, _findAttrOrError(
            templateTTX2, "src")) for templateTTX2 in root.iterfind("./TemplateTTX2")]

    def toBitmapFont(self):
        bitmapfont = BitmapFont(fontinfo=self.fontinfo, outlineCfg=self.outlineCfg,
                                generateBitmap=self.generateBitmap, glyphs=[])
        for glyphsrc in self.glyphsources:
            bitmapfont.appendGlyph(glyphsrc.toGlyph(bitmapfont))

        for gopts, effname, effargs in self.effects:
            for goptname, val in gopts:
                if goptname == "codepoint":
                    glyphs = [bitmapfont.getGlyphByCodepoint(val)]
                    if glyphs[0] is None:
                        log.warn(
                            "glyph to apply effect '{}' (U+{:04x}) was not found.".format(effname, val))
                        continue
                elif goptname == "name":
                    glyphs = [bitmapfont.getGlyphByName(val)]
                    if glyphs[0] is None:
                        log.warn("glyph to apply effect '{}' (name='{}') was not found.".format(
                            effname, val))
                        continue
                elif goptname == "allglyphs":
                    glyphs = bitmapfont.glyphs
                for glyph in glyphs:
                    getattr(glyph.bitmap, effname)(*effargs)

        return bitmapfont

    def shape(self):
        if self.outlineCfg["shapetype"] is not None:
            # if self.outlineCfg["shapetype"] == "pixel-outline":
            shape = DotShapePixelOutline()
        else:
            shape = DotShapeExternal(
                self.outlineCfg["shapesrc"], self.outlineCfg["shapescale_x"], self.outlineCfg["shapescale_y"])

        return shape


_UNIXXXX_REGEXP = re.compile(r"^u(?:ni)?([0-9A-Fa-f]{4,})$")


class GlyphSource(object):
    def __init__(self, bitmapwidth, bitmapheight, advancewidth=0, advanceheight=0, originx=0, originy=0, voriginy=0, name=None, codepoint=-1, effects=None):
        self.bitmapwidth = bitmapwidth
        self.bitmapheight = bitmapheight
        self.advancewidth = advancewidth
        self.advanceheight = advanceheight

        self.origin = (originx, originy)
        self.voriginy = voriginy

        assert name is not None or codepoint != -1

        if name is None and codepoint != -1:
            name = "uni{:04X}".format(codepoint)
        if codepoint == -1:
            m = _UNIXXXX_REGEXP.match(name)
            if m:
                codepoint = int(m.group(1), 16)
        self.name = name
        self.codepoint = codepoint

        if effects is None:
            effects = []
        self.effects = effects

    _glyph = None

    def toGlyph(self, *args, **kwargs):
        if self._glyph is None:
            self._glyph = self._toGlyph(*args, **kwargs)
        return self._glyph


_GBITMAP_IGNORE_REGEXP = re.compile(r"[\t\r\n]+")


class GlyphSourceBitmap(GlyphSource):
    def __init__(self, bitmapstring, bitmapwidth, bitmapheight, *args, **kwargs):
        super(GlyphSourceBitmap, self).__init__(
            bitmapwidth, bitmapheight, *args, **kwargs)
        bitmapstring = _GBITMAP_IGNORE_REGEXP.sub("", bitmapstring)
        bitmap = [
            c not in "0 ." for c in bitmapstring if not 0xDC00 <= ord(c) <= 0xDFFF]
        self.bitmap = [bitmap[i:i + bitmapwidth]
                       for i in range(0, bitmapwidth * bitmapheight, bitmapwidth)]
        self.bitmap.reverse()
        for row in self.bitmap:
            if len(row) < bitmapwidth:
                row += [False] * (bitmapwidth - len(row))

    def _toGlyph(self, font):
        return BitmapGlyph(self.codepoint, self.name, self.bitmap, origin=self.origin, advance=(self.advancewidth, self.advanceheight), voriginy=self.voriginy)


class GlyphSourceSpace(GlyphSourceBitmap):
    def __init__(self, bitmapwidth, bitmapheight, *args, **kwargs):
        super(GlyphSourceSpace, self).__init__("", 1, 1, *args, **kwargs)


class GlyphSourceImage(GlyphSource):
    def __init__(self, src, x, y, *args, **kwargs):
        super(GlyphSourceImage, self).__init__(*args, **kwargs)
        self.src = src
        self.x = x
        self.y = y

    def _toGlyph(self, font):
        w = self.bitmapwidth
        h = self.bitmapheight
        img = getImage(self.src)
        imagedata = list(
            img.crop((self.x, self.y, self.x + w, self.y + h)).getdata())
        bitmap = [[v == 0 for v in imagedata[i:i + w]]
                  for i in range(0, w * h, w)]
        bitmap.reverse()
        return BitmapGlyph(self.codepoint, self.name, bitmap, origin=self.origin, advance=(self.advancewidth, self.advanceheight), voriginy=self.voriginy)


class GlyphSourceGlyph(GlyphSource):
    def __init__(self, srcname=None, srccodepoint=None, *args, **kwargs):
        super(GlyphSourceGlyph, self).__init__(*args, **kwargs)
        self.srcname = srcname
        self.srccodepoint = srccodepoint

    def _toGlyph(self, font):
        assert (self.srcname or self.srccodepoint) is not None
        if self.srcname is not None:
            g = font.getGlyphByName(self.srcname)
        elif self.srccodepoint is not None:
            g = font.getGlyphByCodepoint(self.srccodepoint)
        return BitmapGlyph(self.codepoint, self.name, g.bitmap.bitmap, origin=self.origin, advance=(self.advancewidth, self.advanceheight), voriginy=self.voriginy)


def memoize(f):
    cache = {}

    def _f(*args):
        if args in cache:
            return cache[args]
        v = f(*args)
        cache[args] = v
        return v

    return _f


@memoize
def getImage(path):
    return Image.open(path).convert("L")
