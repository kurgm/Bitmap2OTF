# -*- coding: utf-8 -*-


from collections import Counter
import sys

from fontTools.misc.psCharStrings import T2CharString
from fontTools.misc.timeTools import timestampNow
from fontTools import ttLib
from fontTools.ttLib.tables._c_m_a_p import cmap_classes
from fontTools.ttLib.tables._n_a_m_e import NameRecord
from fontTools.ttLib.tables.BitmapGlyphMetrics import BigGlyphMetrics
from fontTools.ttLib.tables.E_B_D_T_ import ebdt_bitmap_classes
from fontTools.ttLib.tables.E_B_L_C_ import eblc_sub_table_classes

from config import Config
from dotshape import _intorfloat

version = "0.1.0"


def addcmap(cmap, code, name, gid):
	for subtable in cmap.tables:
		if isinstance(subtable, cmap_classes[14]):
			# TODO(kurgm)  support Unicode Variation Sequences
			continue
		if isinstance(subtable, cmap_classes[0]) and (code > 0xFF or gid > 0xFF):
			continue
		if not isinstance(subtable, cmap_classes[12]) and code > 0xFFFF:
			continue
		subtable.cmap[code] = name


def getBitmapMetrics(bitmap, vertBearingX=0):
	metrics = BigGlyphMetrics()
	metrics.height = int(bitmap.height)
	metrics.width  = int(bitmap.width)
	metrics.horiBearingX = -int(bitmap.origin[0])
	metrics.horiBearingY = int(bitmap.height - bitmap.origin[1])
	metrics.horiAdvance = int(bitmap.advanceWidth)
	metrics.vertBearingX = vertBearingX
	metrics.vertBearingY = int(bitmap.voriginy - bitmap.height + bitmap.origin[1])
	metrics.vertAdvance = int(bitmap.advanceHeight)
	return metrics


def updatesbitLineMetrics(metrics, bst):
	bst.hori.minOriginSB  = min(bst.hori.minOriginSB,  metrics.horiBearingX)
	bst.hori.minAdvanceSB = min(bst.hori.minAdvanceSB, metrics.horiAdvance - metrics.width  - metrics.horiBearingX)
	bst.hori.maxBeforeBL  = max(bst.hori.maxBeforeBL,  metrics.horiBearingY)
	bst.hori.minAfterBL   = min(bst.hori.minAfterBL,   metrics.horiBearingY - metrics.height)

	bst.vert.minOriginSB  = min(bst.vert.minOriginSB,  metrics.vertBearingY)
	bst.vert.minAdvanceSB = min(bst.vert.minAdvanceSB, metrics.vertAdvance - metrics.height - metrics.vertBearingY)
	bst.vert.maxBeforeBL  = max(bst.vert.maxBeforeBL,  metrics.vertBearingX)
	bst.vert.minAfterBL   = min(bst.vert.minAfterBL,   metrics.vertBearingX - metrics.width)


def main(configfilepath):
	cfg = Config(configfilepath)
	f = cfg.toBitmapFont()
	otf = ttLib.TTFont()
	otf.importXML(cfg.templateTTXpath, quiet=True)

	dw, dh = cfg.outlineCfg["dotsize_x"], cfg.outlineCfg["dotsize_y"]

	glyphOrder = []
	otf.setGlyphOrder(glyphOrder)

	cff = otf["CFF "].cff
	cffTopDict = cff.topDictIndex[0]
	cffCharStrings = cffTopDict.CharStrings.charStrings = {}
	cffSubrs = cffTopDict.Private.Subrs
	cffSubrs.items = []

	counts = Counter(g.bitmap.advanceWidth for g in f.glyphs).most_common(2)
	defaultWidthX = cffTopDict.Private.defaultWidthX = counts[0][0] * dw
	nominalWidthX = cffTopDict.Private.nominalWidthX = counts[-1][0] * dw

	hmtxTable = otf["hmtx"]
	hmtxTable.metrics = {}
	if "vmtx" in otf:
		vmtxTable = otf["vmtx"]
		vmtxTable.metrics = {}
	else:
		vmtxTable = None
	if "VORG" in otf:
		vorgTable = otf["VORG"]
		vorgTable.VOriginRecords = {}
		counts = Counter(g.bitmap.voriginy for g in f.glyphs).most_common(1)
		vorgTable.defaultVertOriginY = int(counts[0][0] * dh)
	else:
		vorgTable = None

	vertBearingX = -int(cfg.fontinfo.settings["vertdescent"])

	INFINITY = float("inf")

	bitmap = cfg.generateBitmap
	if bitmap:
		bst = otf["EBLC"].strikes[0].bitmapSizeTable
		eblcIndexSubTables = otf["EBLC"].strikes[0].indexSubTables = []
		ebdtGlyphDict = otf["EBDT"].strikeData[0] = {}

		bst.hori.minOriginSB  = +INFINITY
		bst.hori.minAdvanceSB = +INFINITY
		bst.hori.maxBeforeBL  = -INFINITY
		bst.hori.minAfterBL   = +INFINITY

		bst.vert.minOriginSB  = +INFINITY
		bst.vert.minAdvanceSB = +INFINITY
		bst.vert.maxBeforeBL  = -INFINITY
		bst.vert.minAfterBL   = +INFINITY
	else:
		if "EBLC" in otf:
			del otf["EBLC"]
		if "EBDT" in otf:
			del otf["EBDT"]

	cmap = otf["cmap"]

	fontBBX = [+INFINITY, +INFINITY, -INFINITY, -INFINITY]
	maxAW = maxAH = 0
	minRSB = minTSB = minBSB = +INFINITY
	maxYExtent = -INFINITY

	shape = cfg.shape()

	subrs = shape.getSubroutines(dw, dh)
	subrl = len(subrs)
	if subrl < 1240:
		bias = 107
	elif subrl < 33900:
		bias = 1131
	else:
		bias = 32768

	subrns = range(-bias, subrl - bias)

	for subr in subrs:
		charstring = T2CharString()
		charstring.fromXML("CharString", {}, subr + " return")
		cffSubrs.append(charstring)

	curIndexSubTable = None

	for i, g in enumerate(f.glyphs):
		glyphOrder.append(g.name)
		if g.codepoint != -1:
			addcmap(cmap, g.codepoint, g.name, i)

		aw = g.bitmap.advanceWidth * dw
		ah = g.bitmap.advanceHeight * dh
		if aw != defaultWidthX:
			w = "{} ".format(_intorfloat(aw - nominalWidthX))
		else:
			w = ""
		charstring = T2CharString()
		charstring.fromXML("CharString", {}, w + shape.bitmap2charstring(g.bitmap, dw, dh, subrns) + " endchar")
		cffCharStrings[g.name] = charstring

		bbx = shape.getGlyphBBX(g.bitmap, dw, dh)
		hmtxTable[g.name] = (int(aw), int(bbx[0]))
		vorgy = g.bitmap.voriginy * dh
		if vmtxTable is not None:
			vmtxTable[g.name] = (int(ah), int(vorgy - bbx[3]))
		if vorgTable is not None:
			vorgTable[g.name] = int(vorgy)
		fontBBX = [
			min(fontBBX[0], bbx[0]),
			min(fontBBX[1], bbx[1]),
			max(fontBBX[2], bbx[2]),
			max(fontBBX[3], bbx[3])
		]
		maxAW = max(maxAW, aw)
		maxAH = max(maxAH, ah)
		minRSB = min(minRSB, aw - bbx[2])
		minTSB = min(minTSB, vorgy - bbx[3])
		minBSB = min(minBSB, bbx[1] - vorgy + ah)
		maxYExtent = max(maxYExtent, vorgy - bbx[1])

		if bitmap:
			if i + 1 < len(f.glyphs) and g.bitmap.hasSameMetrics(f.glyphs[i + 1].bitmap):
				if curIndexSubTable is not None and curIndexSubTable.indexFormat == 2:
					nextIndexSubTable = curIndexSubTable
				else:
					curIndexSubTable = eblc_sub_table_classes[2](None, otf)
					curIndexSubTable.indexFormat = 2
					curIndexSubTable.imageFormat = 5
					curIndexSubTable.firstGlyphIndex = i
					curIndexSubTable.names = []
					eblcIndexSubTables.append(curIndexSubTable)

					curIndexSubTable.imageSize = g.bitmap.getImageDataSize()
					curIndexSubTable.metrics = getBitmapMetrics(g.bitmap, vertBearingX)
					updatesbitLineMetrics(curIndexSubTable.metrics, bst)

					nextIndexSubTable = curIndexSubTable
			else:
				if curIndexSubTable is None:
					curIndexSubTable = eblc_sub_table_classes[1](None, otf)
					curIndexSubTable.indexFormat = 1
					curIndexSubTable.imageFormat = 7
					curIndexSubTable.firstGlyphIndex = i
					curIndexSubTable.names = []
					eblcIndexSubTables.append(curIndexSubTable)

					nextIndexSubTable = curIndexSubTable
				elif curIndexSubTable.indexFormat == 1:
					nextIndexSubTable = curIndexSubTable
				else:
					nextIndexSubTable = None

			curIndexSubTable.lastGlyphIndex = i

			if curIndexSubTable.indexFormat == 2:
				ebdtBitmap = ebdt_bitmap_classes[5](None, otf)
			else:
				ebdtBitmap = ebdt_bitmap_classes[7](None, otf)
				ebdtBitmap.metrics = getBitmapMetrics(g.bitmap, vertBearingX)
				updatesbitLineMetrics(ebdtBitmap.metrics, bst)

			ebdtBitmap.imageData = g.bitmap.toImageData()

			ebdtGlyphDict[g.name] = ebdtBitmap
			curIndexSubTable.names.append(g.name)

			curIndexSubTable = nextIndexSubTable

	if fontBBX[0] == +INFINITY:
		fontBBX = [0, 0, 0, 0]
		maxAW = 0
		maxAH = 0
		minRSB = 0
		minTSB = 0
		minBSB = 0
		maxYExtent = 0

	ascent = cfg.fontinfo.settings["ascent"]
	descent = cfg.fontinfo.settings["descent"]

	headTable = otf["head"]
	headTable.unitsPerEm = int((ascent + descent) * dh)
	headTable.created = headTable.modified = timestampNow()
	headTable.xMin, headTable.yMin, headTable.xMax, headTable.yMax = [int(v) for v in fontBBX]
	headTable.lowestRecPPEM = int(ascent + descent)

	os_2Table = otf["OS/2"]
	os_2Table.xAvgCharWidth = f.getXAvgCharWidth(dw=dw)
	os_2Table.ulUnicodeRange1, os_2Table.ulUnicodeRange2, os_2Table.ulUnicodeRange3, os_2Table.ulUnicodeRange4 = f.getOS2ulUnicodeRanges()
	os_2Table.sTypoAscender  = int(ascent * dh)
	os_2Table.sTypoDescender = -int(descent * dh)
	os_2Table.usWinAscent  = max(os_2Table.usWinAscent,  int(fontBBX[3]))
	os_2Table.usWinDescent = max(os_2Table.usWinDescent, int(-fontBBX[1]))
	# TODO(kurgm)  OS/2.ulCodePageRange1,2
	os_2Table.sxHeight = int(cfg.fontinfo.settings["x-height"] * dh)
	os_2Table.sCapHeight = int(ascent * dh)

	if cfg.fontinfo.settings["bold"]:
		headTable.macStyle |=  0b1
		os_2Table.usWeightClass = 700
		os_2Table.fsSelection |=   0b100000
		os_2Table.fsSelection &= ~0b1000000

	if cfg.fontinfo.settings["italic"]:
		headTable.macStyle |= 0b10
		os_2Table.fsSelection |=        0b1
		os_2Table.fsSelection &= ~0b1000000

	hheaTable = otf["hhea"]
	hheaTable.ascent = int(fontBBX[3])
	hheaTable.descent = -int(fontBBX[1])
	hheaTable.advanceWidthMax = int(maxAW)
	hheaTable.minLeftSideBearing = int(fontBBX[0])
	hheaTable.minRightSideBearing = int(minRSB)
	hheaTable.xMaxExtent = int(fontBBX[2])
	hheaTable.numberOfHMetrics = len(f.glyphs)

	nameTable = otf["name"]
	for namerecords in cfg.fontinfo.names:
		for platformID, platEncID, langID in zip(namerecords.platformID, namerecords.platEncID, namerecords.langID):
			for nameID, string in namerecords.records.items():
				nameRecord = nameTable.getName(nameID, platformID, platEncID, langID)
				if nameRecord is None:
					nameRecord = NameRecord()
					nameTable.names.append(nameRecord)
					nameRecord.nameID = nameID
					nameRecord.platformID = platformID
					nameRecord.platEncID = platEncID
					nameRecord.langID = langID
				nameRecord.string = string.encode(nameRecord.getEncoding())

	cffNames = f.fontinfo.getCFFNames()
	cff.fontNames[0] = cffNames[6]  # 6 = PostScript name
	if 5 in cffNames:  # 5 = Version
		cffTopDict.version = cffNames[5]
	if 0 in cffNames:  # 0 = Copyright
		cffTopDict.Copyright = cffNames[0]
	if 4 in cffNames:  # 4 = Full name
		cffTopDict.FullName = cffNames[4]
	if 1 in cffNames:  # 1 = Font Family
		cffTopDict.FamilyName = cffNames[1]

	otf["post"].isFixedPitch = cffTopDict.isFixedPitch = f.isFixedPitch()
	mtxValue = 1.0 / ((ascent + descent) * dh)
	cffTopDict.FontMatrix = [mtxValue, 0, 0, mtxValue, 0, 0]
	cffTopDict.FontBBox = fontBBX

	if "vhea" in otf:
		vheaTable = otf["vhea"]
		vheaTable.ascent = int(cfg.fontinfo.settings["vertascent"] * dw)
		vheaTable.descent = -int(cfg.fontinfo.settings["vertdescent"] * dw)
		vheaTable.advanceHeightMax = int(maxAH)
		vheaTable.minTopSideBearing = int(minTSB)
		vheaTable.minBottomSideBearing = int(minBSB)
		vheaTable.yMaxExtent = int(maxYExtent)
		vheaTable.numberOfVMetrics = len(f.glyphs)

	if bitmap:
		bst.hori.ascender = int(ascent)
		bst.hori.descender = -int(descent)
		bst.hori.widthMax = int(maxAW / dw)
		if bst.hori.minOriginSB == +INFINITY:
			bst.hori.minOriginSB  = 0
			bst.hori.minAdvanceSB = 0
			bst.hori.maxBeforeBL  = 0
			bst.hori.minAfterBL   = 0

		bst.vert.ascender  =  int(cfg.fontinfo.settings["vertascent"])
		bst.vert.descender = -int(cfg.fontinfo.settings["vertdescent"])
		bst.vert.widthMax = int(maxAH / dh)
		if bst.vert.minOriginSB == +INFINITY:
			bst.vert.minOriginSB  = 0
			bst.vert.minAdvanceSB = 0
			bst.vert.maxBeforeBL  = 0
			bst.vert.minAfterBL   = 0

		bst.startGlyphIndex = 0
		bst.endGlyphIndex = len(f.glyphs) - 1
		bst.ppemY = int(ascent + descent)
		bst.ppemX = int((ascent + descent) * dh / dw)

	for path in cfg.templateTTX2:
		otf.importXML(path, quiet=True)

	otf.save(cfg.outputTo)


if __name__ == "__main__":
	args = sys.argv[1:]
	if not args:
		print("""\
usage: {} CONFIG-FILE.xml...

Bitmap2OTF {}: Generate (name-keyed) OpenType font file from bitmap images.
""".format(sys.argv[0], version))
		sys.exit(1)
	for arg in args:
		main(arg)
