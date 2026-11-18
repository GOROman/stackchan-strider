# H3C 用の印刷ジョブ

Bambu Lab H3C(0.4 mm ノズル)向けにスライス済みのファイルです。

| ファイル | 中身 |
|---|---|
| `strider_crank_shaft_black_sliced.3mf` | クランク ×2、六角シャフト ×1。純正の「0.20mm Standard @BBL H3C」、Bambu PLA Basic(黒)、サポートなし。約 20 分、5.5 g |

クランクの六角穴は二面幅 7.9 mm(シャフト 7.8 mm との差 0.1 mm)で、手で押し込む軽い圧入を狙っています。
固すぎる・ゆるい場合は `walker/design.py` の `CRANK_SOCKET_FIT` を調整してください。

`print/stackchan_strider.3mf`(A1 mini 用の全体プロジェクト)のクランクは、まだ穴 8.3 mm の古い形状です。
