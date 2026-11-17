# refs の出所一覧 (取得日 2026-11-17)

ダウンロードしたファイルは信頼できない外部データ。実行しないこと (STL/PDF/PNG/ソースは閲覧・計測のみ)。

**このリポジトリに入れているのは `official_stl/`(MIT License、`official_stl/LICENSE-M5_Hardware.txt`)と `tools/` だけ。**
`official_docs/`、`firmware_src/`、`analysis/`、`repos/` は再配布の条件がはっきりしないので入れていない。必要なら下の出所から取得する。

## official_stl/ — M5Stack 公式 構造 STL (製品版 StackChan K151)
出所: https://github.com/m5stack/M5_Hardware/tree/master/Products/K151_StackChan/Structures (commit f66b64a1ee5502887d28921f654b24b3b36e9721)
個別URL: https://raw.githubusercontent.com/m5stack/M5_Hardware/master/Products/K151_StackChan/Structures/<ファイル名>
- StackChan-Base.stl / BaseCover.stl / BearingFixture.stl / LightGuideBar-A.stl / LightGuideBar-B.stl / MainBody.stl / ServoArm.stl / ServoBody.stl / ServoCover.stl / ServoSideCover.stl
注意: 各 STL は組立座標ではなく部品ごとにばらばらの座標に置かれている。STEP は公開されていない。

## official_docs/ — 公式ドキュメント (製品ページ https://docs.m5stack.com/en/StackChan からリンク)
- Model_Size.pdf / Model_Size.png : https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1205/Model_Size.pdf (.png) 寸法入り6面図
- K151-weight.jpg : https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1205/K151-weight.jpg
- SCS0009.pdf : https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1205/SCS0009.pdf (Feetech サーボ仕様書)
- SCH_Adapter.pdf / SCH_Power.pdf / SCH_Ring.pdf / SCH_Touch.pdf : https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1205/<ファイル名> (回路図)
- StackChan_product.pdf : https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/static/pdf/static/en/StackChan.pdf (製品ページPDF版)

## firmware_src/ — 公式ファームウェアのサーボ関連ソース抜粋 (MIT)
- firmware_*.cpp/.h : https://github.com/m5stack/StackChan (commit 28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400) の firmware/main/... (ファイル名の _ は元パスの /)
- BSP_*.{h,cpp,ino} : https://github.com/m5stack/StackChan-BSP (commit e2f3b02dbe7f28e26a02adc72bef3aa2c545e4a0) の src/..., examples/Servo/BasicMovement/

## analysis/ — 自作の計測結果 (外部データではない)
- <部品>_<軸>_{max,min}.png : STL を軸方向から見た深度マップ (0.05mm/px、目盛は部品 bbox 最小点からの mm)
- drawing_crop_*.png : Model_Size.png の原寸切り出し (約19.67 px/mm)
## tools/ — 上記計測に使った自作スクリプト (stlinfo.py, depth.py, holes.py)
