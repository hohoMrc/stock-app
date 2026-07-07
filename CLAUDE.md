# 個人偏好設定

## 語言
- 所有回覆使用**繁體中文**

## 回覆風格
- 採用**逐步引導**方式：每個步驟附上說明，適合建立理解而非只給答案
- 保持回覆簡明，避免不必要的重複說明

## 技術領域
主要工作範圍：
- 後端開發（API、伺服器、資料庫）
- 前端開發（React、Vue、CSS 等）
- AI / ML（模型、推理、資料科學）
- DevOps / 雲端（CI/CD、Docker、雲端服務）
- PHP / Laravel（擅長）

## 程式碼風格
- 加入**適量註解**：重要邏輯或非直覺行為才加，不需要每行都說明
- 避免過度抽象或不必要的重構
- 不加未來用得到的功能，只做當下需要的

---

# 專案背景（台股分析工具）

## 架構概覽
- **後端**：Python，跑在 AWS EC2（`hoho-stock.duckdns.org`，東京區，IP `13.231.218.149`）
- **前端**：React (Vite)，部署在 Vercel，連到上面的 AWS 後端
- **Git repo**：`hohoMrc/stock-app`，push 後 Vercel 自動更新前端；後端需 SSH 進 AWS 手動 git pull + restart

## 部署指令（後端）
```bash
ssh -i ~/.ssh/stock-key ubuntu@13.231.218.149 "cd /home/ubuntu/stock-app && git pull && sudo systemctl restart stock-app"
```

## 主要功能
- 台股 K 線資料存 SQLite DB，每日定時更新（`daily_update`）
- 完成後發 **Telegram 通知**
- **MA 黏合掃描**：先發散再收斂型態，從 DB 全市場掃，不走外部 API
- **週漲幅急漲掃描**：`weekly_scan.py`，條件 ≥20%、日量 ≥1000 張
- 每日排程結束後自動觸發 MA 黏合掃描並 TG 通知
- 成交值排行榜（主要資料來源：Fugle `snapshot/actives`）

## 資料來源
- **Fugle Market Data API**（主力）：即時報價、歷史 K 線、成交排行
- **yfinance**（輔助）：部分功能仍在逐步替換掉
- SQLite DB 為本地快取，盡量從 DB 讀以降低外部 API 依賴

## Fugle API 已使用端點
| 端點 | 用途 |
|------|------|
| `intraday/ticker` | 股票基本資訊、注意/處置旗標 |
| `intraday/quote` | 即時報價、五檔（欄位名 `bids`/`asks`，注意非 `bestBids`） |
| `historical/candles` | 歷史日 K 線（`timeframe=D`） |
| `snapshot/actives` | 成交值排行（type 參數用 `ALLBUT0999`，4個9） |
