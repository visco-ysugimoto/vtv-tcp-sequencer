# VTV TCP Sequencer

VTV-9000 のネットワーク I/O を、ブラウザ上の縦並びカードから実行する
ローカルアプリです。ブラウザと装置の間は Python（FastAPI）が中継します。

## 主な機能

- システムコマンド 43 件のカード
- T001 / T004 / T016 / T018 / T026 / T030 / T034 / T056 /
  T058 / T075 のツール用シリアルコマンド
- OCV の複合コマンド、画像保存先取得時の複数行応答に対応
- システム／ツール別に整理したコマンドパレット
- TCP 接続とリアルタイム送受信ログ
- 順次実行、待機、条件分岐、指定回数ループ
- ドラッグ＆ドロップによるカードの並べ替え・階層間移動
- `NK` / `ER`、タイムアウト、通信・チェックサム異常時の自動停止
- シーケンスの JSON 保存・読込
- 通信ログの TXT / CSV 出力（通信時刻の有無を選択可能）
- 終端、セパレータ、チェックサム、文字コードなどの変更
- PLCLINK（MC 3E 疑似 PLC）接続と D/M 監視
- Field Network（EtherNet/IP Class 1）接続、EDS インポート、アセンブリ監視

## 起動（開発）

PowerShell でプロジェクトフォルダを開き、次を実行します。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python run_app.py
```

または従来どおり:

```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8765
```

`run_app.py` / exe は Edge または Chrome を `--app` モードで開き、
そのウィンドウを閉じるとサーバーも終了します。
（手動起動する場合は Edge / Chrome で <http://127.0.0.1:8765> を開いてください。）

## exe 配布用ビルド

Python が入っている PC で次を実行します。

```powershell
.\build_exe.ps1
```

成果物は `dist\VTV_TCP_Sequencer.zip` です。この ZIP を渡してください。
受け取り側は展開後、`VTV_TCP_Sequencer\VTV_TCP_Sequencer.exe` をダブルクリックで起動します。
コンソールは表示されず、アプリ用ウィンドウを閉じると終了します。
ZIP には `NOTICE_JA.txt`（受け取り側向け注意）と `SHA256.txt`（IT 除外申請用）を同梱します。

### 配布先でのウイルス対策誤検知

**起こりえます。** 自 PC だけでなく、受け取り側でも同様に隔離されることがあります。
原因はアプリの中身ではなく、PyInstaller 製・未署名 exe に対するヒューリスティック判定です。

対策の優先順位:

1. **コード署名（推奨・根本対策）**  
   社内の Authenticode 証明書がある場合、ビルド前に環境変数を設定してから `.\build_exe.ps1` を実行します。

   ```powershell
   $env:VTV_CODESIGN_PFX = "C:\path\to\codesign.pfx"
   $env:VTV_CODESIGN_PASSWORD = "********"
   # 任意: $env:VTV_CODESIGN_TIMESTAMP = "http://timestamp.digicert.com"
   .\build_exe.ps1
   ```

   `signtool.exe`（Windows SDK）が必要です。証明書が無い場合は IT に発行・署名代行を依頼してください。

2. **配布前に IT へ除外申請**  
   `SHA256.txt` のハッシュ、製品名、用途を添えて、会社のウイルス対策（Trend Micro 等）の除外を依頼します。  
   ビルドのたびにハッシュは変わるため、再配布時は再申請が必要なことがあります。

3. **受け取り側での対処（暫定）**  
   - 隔離された exe を復元し、`VTV_TCP_Sequencer` フォルダを除外登録  
   - Windows Defender のみの PC では、同梱の `packaging\Add-DefenderExclusion.ps1` を管理者実行  
   - 詳細は同梱の `NOTICE_JA.txt` を参照

ビルド側の緩和（実施済み）:

- UPX 圧縮を無効化
- PE バージョン情報（製品名・会社名）を埋め込み

注意:

- 受け取り側 PC に Microsoft Edge または Google Chrome が必要です
- PLCLINK 利用時は、Windows ファイアウォールで受信（待受ポート、既定 5000）を許可してください
- PLCLINK 時の VTV 接続先は「この PC の IP:待受ポート」です（装置 IP ではありません）
- Field Network 時は装置 IP:44818 へ Scanner 接続します。VTV で作成した EDS をインポートし、ESI/ESO・コマンド／結果／レスポンス語数を EDS サイズと一致させてください。UDP（Implicit I/O）がファイアウォールで遮断されていないことも確認してください

## 初期設定

### TCP（Network I/O）

- 装置 IP: 空欄
- ポート: `55555`
- タイムアウト: 5 秒（画面上部の **TO** から 0.1〜300 秒で変更可能。接続設定でも同じ値を編集できます）
- 入力終端 / 出力終端: CR
- セパレータ: スペース
- チェックサム: 有効
- 入力応答: 有効
- 文字コード: SJIS（Python の `cp932`）
- 行番号: 2 桁

### PLCLINK（MC 3E 疑似 PLC）

- 待受アドレス: `0.0.0.0`
- 待受ポート: `5000`
- 先に「疑似PLC待受開始」または接続テストを行い、VTV からこの PC へ接続します
- D/M 監視の更新周期: 500 ms 既定（モニター → D/M 監視タブで 10〜10000 ms に変更可能）

### Field Network（EtherNet/IP）

- 装置 IP: VTV の Field Network 用 IP
- ポート: `44818`
- EDS インポートで入力／出力サイズ・RPI・接続パスを反映
- ESI/ESO ポート数、コマンド／レスポンス／結果データ語数は VTV 環境設定と一致させる（割付計算が EDS サイズと一致すること）
- 先に「Field Network 接続」または接続テストを実行

設定はブラウザのローカルストレージに保存されます。

## テスト

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
python -m ruff check .
```

## 注意

`EXP` と `IMP` の詳細構文は C019 マニュアルではなく、別資料
「S002. エクスポート・インポート リファレンスマニュアル」に定義されています。
そのため、この2カードではコマンド名に続く引数を自由入力します。
