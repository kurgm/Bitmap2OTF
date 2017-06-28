# -*- coding: utf-8 -*-

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import json
import logging
import os.path
import re
import sys

from PIL import Image

from bitmapfont import BitmapFont
from bitmapfont import BitmapGlyph
from dotshape import DotShapeExternal
from dotshape import DotShapePixelOutline

log = logging.getLogger(__name__)

PY2 = sys.version_info < (3, 0)

if PY2:
    pass
else:
    basestring = str


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


def getItem(obj, key, objname="object"):
    try:
        return obj[key]
    except KeyError:
        raise ConfigFileError(
            "property '{}' not found in {}".format(key, objname))


def _getGlyphGeometricOptions(obj, default={}):
    res = default.copy()
    for key, val in obj.items():
        if key in ("advancewidth", "advanceheight", "bitmapSize", "origin", "voriginy"):
            res[key] = val
    return res


def _getGlyphSlotInfos(obj):
    if "chars" in obj:
        i = {"codepoint", "name", "char"}.intersection(obj.keys())
        if i:
            raise ConfigFileError(
                "properties 'chars' and '{}' cannot coexist in a glyph source object".format(", ".join(i)))
        chars = obj["chars"]
        if isinstance(chars, list):
            chars = "".join(chars)
        return [{"codepoint": c} for c in _myord(chars)]

    res = {}
    if "name" in obj:
        res["name"] = obj["name"]

    if "codepoint" in obj:
        res["codepoint"] = obj["codepoint"]
    if "char" in obj:
        if "codepoint" in obj:
            raise ConfigFileError(
                "properties 'char' and 'codepoint' cannot coexist in a glyph source object")
        ords = _myord(obj["char"])
        if len(ords) != 1:
            raise ConfigFileError(
                "property 'char' has {} characters".format(len(ords)))
        res["codepoint"] = ords[0]

    if "name" not in res and "codepoint" not in res:
        raise ConfigFileError(
            "Either 'name', 'codepoint', 'char' or 'chars' is required in a glyph source object")

    return [res]


# unused
def _isVariationSelector(code):
    return 0xFE00 <= code <= 0xFE0F or 0xE0100 <= code <= 0xE01EF


def _getEffectTargetInfos(targets):
    res = []
    keys = {"all_glyphs", "name", "codepoint", "char", "chars"}

    if not isinstance(targets, list):
        targets = [targets]

    for target in targets:
        i = keys.intersection(target.keys())
        if len(i) != 1:
            raise ConfigFileError("invalid effect target")
        key = list(i)[0]
        if key == "all_glyphs":
            res.append({"all_glyphs": True})
        elif key == "name":
            res.append({"name": target["name"]})
        elif key == "codepoint":
            res.append({"codepoint": target["codepoint"]})
        elif key == "char":
            ords = _myord(target["char"])
            if len(ords) != 1:
                raise ConfigFileError(
                    "property 'char' has {} characters".format(len(ords)))
            res.append({"codepoint": ords[0]})
        elif key == "chars":
            res.extend({"codepoint": c} for c in _myord(target["chars"]))
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
    def __init__(self, obj={}):
        self.settings = {
            "ascent": 0,
            "descent": 0,
            "x-height": 0,
            "vertascent": 0,
            "vertdescent": 0,
            "bold": 0,
            "italic": 0,
        }
        self.names = []
        self.cffNames = None

        if "settings" in obj:
            self.settings.update(obj["settings"])

        if "namerecords" in obj:
            for record in obj["namerecords"]:
                platformID = getItem(record, "platformID")
                platEncID = getItem(record, "platEncID")
                langID = getItem(record, "langID")

                if not isinstance(platformID, list):
                    platformID = [platformID]
                    platEncID = [platEncID]
                    langID = [langID]

                if not (len(platformID) == len(platEncID) == len(langID)):
                    raise ConfigFileError(
                        "each of platformID, platEncID and langID must have the same number of values")

                records = {}
                for keyword, value in record["namerecord"].items():
                    if keyword.isdigit():
                        nameID = int(keyword)
                    else:
                        nameID = _nameKeyword2nameID.get(keyword.lower())
                        if nameID is None:
                            log.warn(
                                "ignoring unknown keyword '{}' in namerecord.".format(keyword))
                            continue
                    records[nameID] = value

                self.names.append(NameRecord(
                    platformID, platEncID, langID, records))

                if record.get("useAsCFFNames", False):
                    self.cffNames = records

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

        with open(configfilepath, "r") as configfile:
            config = json.load(configfile)

        if "ttx" in config:
            templates = config["ttx"]
            if isinstance(templates, basestring):
                templates = [templates]
            self.templates = [os.path.join(configdirpath, path)
                              for path in templates]
        else:
            # FIXME
            raise ConfigFileError("No template found")

        if "output" in config:
            self.outputTo = os.path.join(configdirpath, config["output"])
        else:
            self.outputTo = os.path.splitext(configfilepath)[0] + ".otf"

        fontinfo = getItem(config, "fontInfo")
        self.fontinfo = FontInfo(fontinfo)

        self.outlineCfg = {
            "dotSize": [100, 100],
            "dotShape": "pixel-outline",
        }
        self.outlineCfg.update(getItem(config, "outline"))

        dotshape = self.outlineCfg["dotShape"]
        if isinstance(dotshape, basestring):
            if dotshape != "pixel-outline":
                raise ConfigFileError(
                    "unknown dot shape type '{}'".format(dotshape))
        else:
            dotshape["src"] = os.path.join(
                configdirpath, getItem(dotshape, "src", "dotShape"))
            dotshape.setdefault("scale", [1.0, 1.0])

        self.generateBitmap = config.get("bitmap", False)

        glyphsrcs = getItem(config, "glyphs")
        self.glyphsources = []

        source_classes = {
            "data": GlyphSourceBitmap,
            "space": GlyphSourceSpace,
            "image": GlyphSourceImage,
            "copy": GlyphSourceGlyph,
        }
        default_geometry = _getGlyphGeometricOptions(glyphsrcs)
        for glyphsrc in getItem(glyphsrcs, "sources", "glyphs object"):
            glyph_settings = _getGlyphGeometricOptions(
                glyphsrc, default_geometry)
            glyph_slots = _getGlyphSlotInfos(glyphsrc)
            i = set(source_classes.keys()).intersection(glyphsrc.keys())
            if len(i) != 1:
                raise ConfigFileError("Invalid glyph source")
            source_type = list(i)[0]
            klass = source_classes[source_type]
            opts = glyphsrc[source_type]
            glyphs = klass.parse_config(
                opts, slots=glyph_slots, opts=glyph_settings, basepath=configdirpath)
            self.glyphsources.extend(glyphs)

        self.effects = []
        effects = config.get("effects", [])
        effectNames = {"makebold", "makeitalic",
                       "translate", "rotate", "scale"}
        for effect in effects:
            i = effectNames.intersection(effect.keys())
            if not i:
                logging.warn("ignoring unknown effect")
                continue
            if len(i) > 1:
                raise ConfigFileError(
                    "multiple effects ({}) cannot be applied at once".format(", ".join(i)))
            effectName = list(i)[0]
            effectValue = effect[effectName]
            targets = _getEffectTargetInfos(getItem(effect, "target"))
            if effectName == "makebold":
                self.effects.append([targets, effectName, [
                    effectValue.get("boldtype", 0),
                    effectValue.get("x", 1),
                    effectValue.get("y", 0),
                    effectValue.get("x2", 0),
                    effectValue.get("y2", 0)
                ]])
            if effectName == "makeitalic":
                self.effects.append([targets, effectName, effectValue])
            if effectName == "translate":
                self.effects.append([targets, effectName, effectValue])
            if effectName == "rotate":
                self.effects.append([targets, effectName, effectValue])
            if effectName == "scale":
                self.effects.append([targets, effectName, effectValue])

        after_templates = config.get("ttx_after", [])
        if isinstance(after_templates, basestring):
            after_templates = [after_templates]
        self.templateTTX2 = [os.path.join(configdirpath, path)
                             for path in after_templates]

    def toBitmapFont(self):
        bitmapfont = BitmapFont(fontinfo=self.fontinfo, outlineCfg=self.outlineCfg,
                                generateBitmap=self.generateBitmap, glyphs=[])
        for glyphsrc in self.glyphsources:
            bitmapfont.appendGlyph(glyphsrc.toGlyph(bitmapfont))

        for gopts, effname, effargs in self.effects:
            for gopt in gopts:
                if "codepoint" in gopt:
                    codepoint = gopt["codepoint"]
                    glyphs = [bitmapfont.getGlyphByCodepoint(codepoint)]
                    if glyphs[0] is None:
                        log.warn(
                            "glyph to apply effect '{}' (U+{:04x}) was not found.".format(effname, codepoint))
                        continue
                elif "name" in gopt:
                    name = gopt["name"]
                    glyphs = [bitmapfont.getGlyphByName(name)]
                    if glyphs[0] is None:
                        log.warn("glyph to apply effect '{}' (name='{}') was not found.".format(
                            effname, name))
                        continue
                elif "all_glyphs" in gopt:
                    glyphs = bitmapfont.glyphs
                for glyph in glyphs:
                    getattr(glyph.bitmap, effname)(*effargs)

        return bitmapfont

    def shape(self):
        dotShape = self.outlineCfg["dotShape"]
        if isinstance(dotShape, basestring):
            # if dotShape == "pixel-outline":
            shape = DotShapePixelOutline()
        else:
            shape = DotShapeExternal(dotShape["src"], dotShape["scale"])

        return shape


_UNIXXXX_REGEXP = re.compile(r"^u(?:ni)?([0-9A-Fa-f]{4,})$")


class GlyphSource(object):
    def __init__(self, slot, opts):
        self.bitmapSize = getItem(opts, "bitmapSize")
        self.advancewidth = opts.get("advancewidth", 0)
        self.advanceheight = opts.get("advanceheight", 0)

        self.origin = opts.get("origin", [0, 0])
        self.voriginy = opts.get("voriginy", 0)

        name = slot.get("name", None)
        codepoint = slot.get("codepoint", -1)
        assert name is not None or codepoint != -1

        if name is None and codepoint != -1:
            name = "uni{:04X}".format(codepoint)
        if codepoint == -1:
            m = _UNIXXXX_REGEXP.match(name)
            if m:
                codepoint = int(m.group(1), 16)
        self.name = name
        self.codepoint = codepoint

        self.effects = []

    _glyph = None

    def toGlyph(self, *args, **kwargs):
        if self._glyph is None:
            self._glyph = self._toGlyph(*args, **kwargs)
        return self._glyph


class GlyphSourceBitmap(GlyphSource):
    def __init__(self, bitmap, slot, opts):
        super(GlyphSourceBitmap, self).__init__(slot, opts)
        bitmapwidth, bitmapheight = self.bitmapSize
        if len(bitmap) < bitmapheight:
            bitmap.extend([] for i in range(bitmapheight - len(bitmap)))
        for row in bitmap:
            if len(row) < bitmapwidth:
                row += [False] * (bitmapwidth - len(row))
        bitmap.reverse()
        self.bitmap = bitmap

    def _toGlyph(self, font):
        return BitmapGlyph(self.codepoint, self.name, self.bitmap, origin=self.origin, advance=(self.advancewidth, self.advanceheight), voriginy=self.voriginy)

    @classmethod
    def data2bitmap(cls, data, opts):
        bitmapwidth, bitmapheight = opts.get("bitmapSize", [0, 0])
        if isinstance(data, basestring):
            bits = [c not in "0 ." for c in data
                    if c not in "\t\r\n" and not 0xDC00 <= ord(c) <= 0xDFFF]
            return [bits[i:i + bitmapwidth]
                    for i in range(0, bitmapwidth * bitmapheight, bitmapwidth)]
        return [
            [c not in "0 ." for c in row
             if c not in "\t\r\n" and not 0xDC00 <= ord(c) <= 0xDFFF]
            if isinstance(row, basestring) else [bool(c) for c in row]
            for row in data]

    @classmethod
    def parse_config(cls, obj, slots, opts, basepath=""):
        return [cls(cls.data2bitmap(obj, opts), slot=slot, opts=opts) for slot in slots]


class GlyphSourceSpace(GlyphSourceBitmap):
    def __init__(self, slot, opts):
        opts["bitmapSize"] = [1, 1]
        super(GlyphSourceSpace, self).__init__([[False]], slot, opts)

    @classmethod
    def parse_config(cls, obj, slots, opts, basepath=""):
        return [cls(slot=slot, opts=opts) for slot in slots]


class GlyphSourceImage(GlyphSource):
    def __init__(self, src, pos, slot, opts):
        super(GlyphSourceImage, self).__init__(slot, opts)
        self.src = src
        self.pos = pos

    def _toGlyph(self, font):
        w, h = self.bitmapSize
        x, y = self.pos
        img = getImage(self.src)
        imagedata = list(img.crop((x, y, x + w, y + h)).getdata())
        bitmap = [[v == 0 for v in imagedata[i:i + w]]
                  for i in range(0, w * h, w)]
        bitmap.reverse()
        return BitmapGlyph(self.codepoint, self.name, bitmap, origin=self.origin, advance=(self.advancewidth, self.advanceheight), voriginy=self.voriginy)

    @classmethod
    def parse_config(cls, obj, slots, opts, basepath):
        x, y = getItem(obj, "pos")
        src = getItem(obj, "src")
        glyphs = []
        x0 = x
        assert len(slots) > 0
        if len(slots) == 1:
            return [cls(os.path.join(basepath, src), [x, y], slot=slots[0], opts=opts)]

        dx, dy = getItem(obj, "step")
        charsperrow = getItem(obj, "charsPerRow")

        for i, slot in enumerate(slots):
            glyphs.append(cls(os.path.join(basepath, src),
                              [x, y], slot=slot, opts=opts))
            if (i + 1) % charsperrow == 0:
                x = x0
                y += dy
            else:
                x += dx
        return glyphs


class GlyphSourceGlyph(GlyphSource):
    def __init__(self, src, slot, opts):
        super(GlyphSourceGlyph, self).__init__(slot=slot, opts=opts)
        self.src = src

    def _toGlyph(self, font):
        if "name" in self.src:
            g = font.getGlyphByName(self.src["name"])
        elif "codepoint" in self.src:
            g = font.getGlyphByCodepoint(self.src["codepoint"])
        return BitmapGlyph(self.codepoint, self.name, g.bitmap.bitmap, origin=self.origin, advance=(self.advancewidth, self.advanceheight), voriginy=self.voriginy)

    @classmethod
    def parse_config(cls, obj, slots, opts, basepath=""):
        if "fromChar" in obj:
            ords = _myord(obj["fromChar"])
            if len(ords) != 1:
                raise ConfigFileError(
                    "'fromChar' property has {} characters".format(len(ords)))
            src = {"codepoint": ords[0]}
        elif "fromCodepoint" in obj:
            src = {"codepoint": obj["fromCodepoint"]}
        elif "fromName" in obj:
            src = {"name": obj["fromName"]}
        else:
            raise ConfigFileError(
                "fromChar, fromCodepoint or fromName property is required in a 'copy' source object")
        return [cls(src, slot=slot, opts=opts) for slot in slots]


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
