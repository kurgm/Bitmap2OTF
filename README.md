# Bitmap2OTF
画像ファイルからビットマップ風の (name-keyed) OpenType フォントを生成します

## 要件
Bitmap2OTF の実行には以下のソフトウェアとライブラリが必要です:

- Python 2.7
- [fontTools](https://github.com/behdad/fonttools)
- [Python Imaging Library (PIL)](http://www.pythonware.com/products/pil/)

## 使い方
`python bitmap2otf.py PARAMETER-FILE.json`

`PARAMETER-FILE.json` は XML-ベースのパラメータファイルです。サンプルは
`sample/sample.json` にあります。

## ライセンス
このソフトウェアは MIT License のもとで公開しています。`LICENSE`
ファイルを参照してください。
