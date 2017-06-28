# -*- coding: utf-8 -*-

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import logging

from bitmap import Bitmap

log = logging.getLogger(__name__)


class BitmapFont(object):

    def __init__(self, fontinfo, outlineCfg, generateBitmap=True, glyphs=[]):
        self.fontinfo = fontinfo
        self.outlineCfg = outlineCfg
        self.generateBitmap = generateBitmap

        self.glyphs = list(glyphs)

    def appendGlyph(self, glyph):
        if self.getGlyphByName(glyph.name) is not None:
            if glyph.name != "uni0020":
                log.info("there is already a glyph with name '{}' in the font and the new glyph was not added.".format(
                    glyph.name))
            return
        if glyph.codepoint != -1 and self.getGlyphByCodepoint(glyph.codepoint) is not None:
            log.info(
                "there is already a glyph with codepoint U+{:04x} in the font and the new glyph was not added.".format(glyph.codepoint))
            return
        self.glyphs.append(glyph)

    def getGlyphByName(self, name):
        for g in self.glyphs:
            if g.name == name:
                return g
        return None

    def getGlyphByCodepoint(self, codepoint):
        for g in self.glyphs:
            if g.codepoint == codepoint:
                return g
        return None

    # OS/2 table

    def getXAvgCharWidth(self, dw=100.0):
        # this is not the correct way of calculating xAvgCharWidth...
        aws = [g.bitmap.advanceWidth
               for g in self.glyphs
               if 0x61 <= g.codepoint <= 0x7A or g.codepoint == 0x20]
        if not aws:
            return 0
        return int(sum(aws) * dw / len(aws))

    # post table

    def isFixedPitch(self):
        nonzeroWidths = [
            g.bitmap.advanceWidth for g in self.glyphs if g.bitmap.advanceWidth != 0]
        if not nonzeroWidths:
            return True
        w0 = nonzeroWidths[0]
        return all(w == w0 for w in nonzeroWidths[1:])


class BitmapGlyph(object):
    """Bitmap with name and codepoint"""

    def __init__(self, codepoint, name, bitmap=[[]], *args, **kwargs):
        self.codepoint = codepoint
        self.name = name
        if isinstance(bitmap, Bitmap):
            self.bitmap = bitmap
        else:
            self.bitmap = Bitmap(bitmap, *args, **kwargs)
