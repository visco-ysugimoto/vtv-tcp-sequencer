# リファレンス資料の置き場

ツールごとのシリアルコマンドをカタログ化するときの参照先です。  
ここに PDF を置いていただけると、システムコマンドと同様に実装できます。

## 推奨配置

```
docs/reference/
  C019_Serial_NetworkIO-JP.pdf          # 全体概要・システム/ツールの索引
  S002_Export_Import-JP.pdf             # EXP / IMP（任意）
  tools/
    T001_ImageAcquisition-JP.pdf
    T004_MultiCoordinateSystem-JP.pdf
    T016_Character-JP.pdf
    T018_DefFinder-JP.pdf
    T034_OCV-JP.pdf
    T046_SerialOutput-JP.pdf            # 必要なら
    T056_MatrixDefFinder-JP.pdf
    T058_SegmentDefFinder-JP.pdf
    T075_DistributionProcessing-JP.pdf
    …（他ツール資料）
```

## C019 4.2 で参照されている主な資料

| ツール | 想定資料 |
|--------|----------|
| 画像取込 | T001 |
| OCV | T034 |
| 文字検査／パターン検査 | T016 |
| DefFinder 系 | T018 |
| マルチ座標系 | T004 |
| MatrixDefFinder | T056 |
| SegmentDefFinder | T058 |
| 計測編集 | 該当ツール資料 |
| 画像+図形参照表示 | 該当ツール資料 |
| 分配処理 | T075 |

ファイル名は社内命名（`VTV9000-Reference-T00x_...-JP.pdf` など）のままで構いません。  
`tools/` 配下に置けば問題ありません。

## 注意

- 資料は社内リファレンスのため、Git に載せる必要がなければ `.gitignore` に追加してください。
- 実装側の成果物は `backend/catalog/` 配下の JSON（例: `tool_commands.json`）に集約する想定です。
