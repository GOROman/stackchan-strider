# Stackchan Strider ファームウェア

M5Stack 製品版スタックチャン (K151 / CoreS3) を、首振りサーボの連続回転で歩かせるファームウェアです。MacBook Pro のネイティブアプリから Bluetooth で直接操作できます。本体の画面にはスタックチャンの顔が表示され、起動時に顔の上下角度を中央の 30° に戻します。

## Mac から操作する

Mac のターミナルでリポジトリのルートからネイティブアプリをビルドして開きます。ビルドには Xcode Command Line Tools が必要です。

```sh
firmware/mac/build.sh
open "firmware/.pio/mac/Stackchan Strider.app"
```

1. 「Bluetooth で接続」をクリックします。macOS が Bluetooth へのアクセスを求めたら許可してください。
2. カーソルを縦スライダーの上に置きます。MacBook Pro のトラックパッドに置いた最初の指を上に動かすと前進し、下に動かすと後退します。指を離すと約 0.32 秒で減速して停止し、つまみが中央に戻ります。クリックしたままドラッグしても操作できます。
3. 歩行を操作している間、2 本目の指を上下に動かすと顔の上下角度を調整できます。

Wi-Fi の設定は不要です。

| 操作 | 動き |
| --- | --- |
| 縦スライダー | 中央から離すほど速くなり、前進・後退ともに 10〜100% を 1% 刻みで調整 |
| 顔の上下角度スライダー | 0〜60° を 1° 刻みで調整 |
| 前進と後退を入れ替える | 本体に設定を保存 |
| センタリング | 歩行を停止し、顔の上下角度を 30° に戻す |
| 歩行に合わせて表情と顔を動かす | 前進時は正面寄り、後退時は素早く上向きになる。歩行中は首振りサーボの実測角度を使い、クランクの回転位置に合わせて頭を上下させる。停止すると指定した角度に戻る。速度や加速に応じて真剣な顔や驚いた顔になる。初期状態はオン |

アプリはスライダーを操作している間、約 0.3 秒ごとにコマンドを送ります。接続が切れるか、コマンドが 0.9 秒途切れると本体が停止します。初回は脚を浮かせて、押すと動き、離すと止まることを確認してください。

## 書き込む前に

- 書き込むと、出荷時のアプリ(AI エージェントなど)は起動しなくなる。元に戻すには、下の「元に戻す」の手順でバックアップを書き戻すか、M5Burner で公式ファームウェアを書き直す。
- CoreS3 の電源を入れてからパソコンにつなぐ。「USB シリアル デバイス (COMx)」として見える(ESP32-S3 の USB-JTAG/シリアル)。

## 書き込み

**アプリ本体だけを `0x20000`(出荷時の 1 番目のアプリ領域 ota_0)に書く。** ブートローダー・領域配置・設定領域(NVS)は出荷時のまま残す。NVS にはサーボの原点調整値(名前空間 `servo`)が入っているので、消さない。

PowerShell で実行する(Git Bash では ESP32 のツール導入が失敗する)。COM8 は実際のポート番号に置き換える。

```
cd firmware
pio run
$py = "$env:USERPROFILE\.platformio\penv\Scripts\python.exe"
& $py -m esptool --chip esp32s3 --port COM8 --baud 921600 write-flash 0x20000 .pio\build\stackchan\firmware.bin
```

Mac ではビルド後に以下のように書き込みます。ポート名は実機に合わせて変更してください。

```sh
cd firmware
pio run
~/.platformio/penv/bin/python -m esptool --chip esp32s3 --port /dev/cu.usbmodem101 --baud 921600 write-flash 0x20000 .pio/build/stackchan/firmware.bin
```

ビルド済みのアプリ(`stackchan-strider-app.bin`、書き込み先 `0x20000`)は、GitHub の Releases に置く。

注意:
- `pio run -t upload` と、ビルドで出来る `firmware.factory.bin` は使わない。PlatformIO は起動スロット情報を `0xe000` に書くが、この機体の領域配置では `0xd000` にあり、ずれる。
- 出荷時の起動スロットが ota_0 であることが前提(2026-11-17 の個体では、otadata の世代番号が 3 と 2 で ota_0 が選ばれていた)。公式ファームウェアをオンライン更新した直後などで ota_1 から起動している個体では、`0x20000` に書いても出荷時アプリが起動する。その場合は otadata を初期化する(`boot_app0.bin` を `0xd000` に書く)。
- 領域配置は `partitions_stackchan.csv`(出荷時と同じ)。暗号化とセキュアブートは無効であることを確認済み。

## 元に戻す

**書き込む前に、自分の機体の出荷時の内容(16MB)を丸ごと読み出して保存しておく。** 数分かかる。

```
& $py -m esptool --chip esp32s3 --port COM8 --baud 921600 read-flash 0x0 0x1000000 backup\stackchan_factory_flash_16MB.bin
```

元に戻すときは、保存したファイルを先頭から書き戻す。

```
& $py -m esptool --chip esp32s3 --port COM8 --baud 921600 write-flash 0x0 backup\stackchan_factory_flash_16MB.bin
```

バックアップには、その機体の設定(保存済みの Wi-Fi など)が入りうるので、人に渡したり公開したりしない。

## ビルド環境

- PlatformIO + pioarduino(Arduino-ESP32 3 系)。公式の StackChan-BSP が ESP-IDF 5 の API を使うため、PlatformIO 標準の環境(2 系)ではコンパイルできない。
- 依存: StackChan-BSP 1.1.1(コミット e2f3b02)、M5Unified 0.3.0、M5GFX 0.3.0、M5Stack-Avatar 0.10.0、IRremoteESP8266、M5Unit-NFC。
- `src/main.cpp` が BLE と本体の動作を、`mac/` が Mac の操作アプリを担当します。
