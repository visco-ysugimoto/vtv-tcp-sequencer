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

注意:

- 受け取り側 PC に Microsoft Edge または Google Chrome が必要です
- 初回起動時にウイルス対策ソフトが警告することがあります

## 初期設定

- 装置 IP: 空欄
- ポート: `55555`
- タイムアウト: 5 秒
- 入力終端 / 出力終端: CR
- セパレータ: スペース
- チェックサム: 有効
- 入力応答: 有効
- 文字コード: SJIS（Python の `cp932`）
- 行番号: 2 桁

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
