# EC2 主機環境

`hoho-stock.duckdns.org`（IP `13.231.218.149`，東京 `ap-northeast-1c`）。crontab 本身沒有版控，這份文件是唯一備份，改動排程時記得同步更新。

紀錄時間：2026-09-19。機型/OS 這類資訊會隨時間變動，用之前先 SSH 上去用下方指令現場確認，不要直接假設這份文件還準確。

## 硬體規格

| 項目 | 內容 |
|---|---|
| 機型 | AWS EC2 `t3.micro`（2 vCPU, 908MB RAM） |
| OS | Ubuntu 26.04 LTS |
| 硬碟 | 6.7GB（記錄當下已用 74%） |

確認指令：
```bash
ssh -i ~/.ssh/stock-key ubuntu@13.231.218.149 "free -h; df -h /; nproc"
```

**已知瓶頸（2026-09-19）**：RAM 只剩 ~110MB 空閒、硬碟剩 1.8GB，偏緊繃。這台機器同時跑了跟 stock-app 無關的 `invoice-bot`（LINE 發票機器人），兩個服務共用 1GB RAM。若之後又變緊繃，優先考慮把 `invoice-bot` 移到別台機器，或升級機型（t3.micro → t3.small）。

## 常駐服務（systemd）

| Service | 用途 |
|---|---|
| `stock-app.service` | 本專案後端（FastAPI/uvicorn），對應這份 repo |
| `invoice-bot.service` | 不相關的 LINE 發票機器人，共用同一台機器 |
| `caddy` | 反向代理 / HTTPS |
| `cron` | 排程 |

部署指令見 `CLAUDE.md`「部署指令（後端）」章節。

## 排程（crontab，未版控）

台灣時間：

| 時間 | 腳本 | 用途 |
|---|---|---|
| 週一~五 15:30 | `daily_update.py` | 每日股票資料更新（K線、掃描、Telegram通知） |
| 週六 09:00 | `weekly_scan.py` | 週漲幅急漲掃描（≥20%、日量≥1000張） |
| 週二~六 05:30 | `night_update.py` | 期貨夜盤資料更新 |
| 週一~五 07:30 | `news_update.py` | 新聞摘要更新 |
| 週一~五 09:00-13:00 每2分 | `alert_price_check.py` | 個人化價格提醒檢查 |
| 週一~五 08:00-13:00,15:00-23:00；週二~六 00:00-05:00 每2分 | `futures_conditional_check.py` | 期貨條件單檢查 |
| 週一~五 09:00-13:00 每2分 | `stock_conditional_check.py` | 股票條件單檢查 |
| 週一~五 09:00-13:00 每2分 | `day_trading_check.py` | 當沖條件檢查 |
| 週一~五 08:00-13:00,15:00-23:00；週二~六 00:00-05:00 每2分 | `futures_ema_alert_check.py` | 微台指(TMF)觸及EMA126(1分K)即發Telegram通知 |
| 每6小時 | — | 清理 `backend/log/` 下超過1天的 Fugle/Fubon SDK log（`program.log.*`／`notify.log.*`／`client.log.*`） |

確認/編輯指令：
```bash
ssh -i ~/.ssh/stock-key ubuntu@13.231.218.149 "crontab -l"
ssh -i ~/.ssh/stock-key ubuntu@13.231.218.149 "crontab -e"   # 互動編輯，改完記得回來更新這份文件
```

這些排程腳本本身不寫執行紀錄到 DB（只印 stdout + 發 Telegram），若懷疑排程斷更，用系統監控頁（前端「監控」分頁，`/api/system/status`）看各資料表最新日期反推，或直接 `tail /home/ubuntu/logs/<script>.log`。
