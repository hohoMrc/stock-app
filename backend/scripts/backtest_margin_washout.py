"""
「超跌＋融資清洗」回測：股價 20 日內跌超過 20%、融資餘額從近期高點砍掉 25% 以上的股票，
之後是否真的比較會反彈（籌碼乾淨 → 反彈主攻）。

用法：
  python3 scripts/backtest_margin_washout.py fetch   # 補抓 2021~2026/07 歷史融資餘額進 backtest_cache.db（可中斷續抓）
  python3 scripts/backtest_margin_washout.py run     # 跑回測

設計重點：
- 訊號在 t 日收盤後才知道（融資資料晚上才公布），所以 t+1 開盤進場，看持有 5／10／20 個交易日後的收盤報酬
- 對照組：同樣跌超過 20%、但融資幾乎沒減的股票——用來分辨「融資清洗」本身有沒有加分，而不只是「跌深反彈」
- 超額報酬：同一段期間（t+1 開盤 → 同一天收盤）全市場有量股票的等權平均報酬
- 窗口內任一天漲跌超過 10.5%（漲跌停是 10%）視為減資／除權等公司行動，整筆略過
- 同一檔同一組訊號觸發後 20 個交易日內不重複計算
"""
import os
import sqlite3
import statistics as st
import sys
import time
from collections import defaultdict

import requests

BACKEND = os.path.join(os.path.dirname(__file__), "..")
MAIN_DB = os.path.join(BACKEND, "stock_cache.db")
CACHE_DB = os.path.join(BACKEND, "backtest_cache.db")

FETCH_START, FETCH_END = "2021-01-04", "2026-07-18"   # 正式 DB 的融資資料從 2026-07-19 開始
HEADERS = {"User-Agent": "Mozilla/5.0"}

DROP_20D = -0.20        # 20 日跌幅門檻
MARGIN_LOOKBACK = 25    # 融資高點回看天數
MIN_AVG_VOL = 500       # 20 日均量（張）
MIN_MARGIN = 1000       # 融資高點至少幾張，太小的融資變化沒有意義
COOLDOWN = 20
HORIZONS = (5, 10, 20)
COST = 0.001425 * 2 + 0.003   # 來回手續費＋證交稅
GROUPS = [("A 融資清洗 ≤-25%", -1.0, -0.25), ("B 融資小減 -25~-10%", -0.25, -0.10), ("C 融資沒減 >-10%（對照）", -0.10, 9.0)]


def trading_days(main) -> list[str]:
    return [r[0] for r in main.execute(
        "SELECT date FROM candles GROUP BY date HAVING COUNT(*) > 1000 ORDER BY date")]


def num(s) -> int | None:
    try:
        return int(str(s).replace(",", "").strip())
    except ValueError:
        return None


# ── 抓歷史融資 ───────────────────────────────────────────────

def open_cache():
    c = sqlite3.connect(CACHE_DB)
    c.execute("CREATE TABLE IF NOT EXISTS margin_hist (ticker TEXT, date TEXT, balance INTEGER, quota INTEGER, "
              "PRIMARY KEY (ticker, date))")
    c.execute("CREATE TABLE IF NOT EXISTS margin_fetched (date TEXT, src TEXT, n INTEGER, PRIMARY KEY (date, src))")
    return c


def fetch_twse(day: str) -> list[tuple]:
    j = requests.get("https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN",
                     params={"date": day.replace("-", ""), "selectType": "ALL", "response": "json"},
                     headers=HEADERS, timeout=30).json()
    if j.get("stat") != "OK":
        return []
    t = next(t for t in j["tables"] if "彙總" in t.get("title", ""))
    return [(r[0].strip(), day, num(r[6]), num(r[7])) for r in t["data"]]   # 融資今日餘額、次一營業日限額


def fetch_tpex(day: str) -> list[tuple]:
    j = requests.get("https://www.tpex.org.tw/www/zh-tw/margin/balance",
                     params={"date": day.replace("-", "/"), "response": "json"}, headers=HEADERS, timeout=30).json()
    rows = j["tables"][0]["data"] if j.get("tables") else []
    return [(r[0].strip(), day, num(r[6]), num(r[9])) for r in rows]        # 資餘額、資限額


def fetch():
    main = sqlite3.connect(MAIN_DB)
    cache = open_cache()
    done = set(cache.execute("SELECT date, src FROM margin_fetched"))
    days = [d for d in trading_days(main) if FETCH_START <= d <= FETCH_END]
    todo = [(d, s) for d in days for s in ("twse", "tpex") if (d, s) not in done]
    print(f"共 {len(days)} 個交易日，待抓 {len(todo)} 筆", flush=True)
    for i, (day, src) in enumerate(todo, 1):
        for attempt in range(4):
            try:
                rows = (fetch_twse if src == "twse" else fetch_tpex)(day)
                break
            except Exception as e:
                print(f"{day} {src} 失敗({attempt + 1}): {e}", flush=True)
                time.sleep(20 * (attempt + 1))   # 證交所會擋太密集的請求，失敗就等久一點
        else:
            continue
        rows = [r for r in rows if r[0].isdigit() and len(r[0]) == 4]
        cache.executemany("INSERT OR REPLACE INTO margin_hist VALUES (?,?,?,?)", rows)
        cache.execute("INSERT OR REPLACE INTO margin_fetched VALUES (?,?,?)", (day, src, len(rows)))
        cache.commit()
        if i % 50 == 0:
            print(f"[{i}/{len(todo)}] {day} {src} {len(rows)} 檔", flush=True)
        time.sleep(2.5)
    print("完成", flush=True)


# ── 回測 ─────────────────────────────────────────────────────

def load_ticker(main, cache, t: str, days: list[str]):
    rows = main.execute("SELECT date, open, close, volume FROM candles WHERE ticker=? AND date>=? ORDER BY date",
                        (t, days[0])).fetchall()
    by = {d: (o, c, v / 1000) for d, o, c, v in rows if o and c}   # volume 是股數，換成張
    mg = dict(cache.execute("SELECT date, balance FROM margin_hist WHERE ticker=?", (t,)))
    mg.update(main.execute("SELECT date, margin_balance FROM margin_trading WHERE ticker=?", (t,)).fetchall())
    seq = [(d, *by[d], mg.get(d)) for d in days if d in by]   # 只用真正交易日，休市日的重複融資資料不會混進來
    return seq


def fwd(seq, i, n):
    """t+1 開盤進場、第 n 個交易日收盤出場的報酬；資料不夠或碰到公司行動回 None"""
    if i + n >= len(seq):
        return None
    for k in range(i + 1, i + n + 1):
        if abs(seq[k][2] / seq[k - 1][2] - 1) > 0.105:
            return None
    return seq[i + n][2] / seq[i + 1][1] - 1


def run():
    main = sqlite3.connect(MAIN_DB)
    cache = open_cache()
    days = [d for d in trading_days(main) if d >= "2020-11-01"]
    tickers = [r[0] for r in main.execute(
        "SELECT DISTINCT ticker FROM candles WHERE date>=? AND ticker GLOB '[1-9][0-9][0-9][0-9]'", (days[0],))]

    # 第一輪：全市場等權基準（每天的前瞻報酬、近 20 日報酬）
    base = defaultdict(lambda: defaultdict(list))
    seqs_ok = []
    for t in tickers:
        seq = load_ticker(main, cache, t, days)
        if len(seq) < 60:
            continue
        seqs_ok.append(t)
        for i in range(20, len(seq)):
            avgv = sum(x[3] for x in seq[i - 19:i + 1]) / 20
            if avgv < MIN_AVG_VOL:
                continue
            for n in HORIZONS:
                r = fwd(seq, i, n)
                if r is not None:
                    base[seq[i][0]][n].append(r)
            base[seq[i][0]]["r20"].append(seq[i][2] / seq[i - 20][2] - 1)
    bmean = {d: {k: sum(v) / len(v) for k, v in m.items() if v} for d, m in base.items()}
    print(f"股票 {len(seqs_ok)} 檔，基準日 {len(bmean)} 天", flush=True)

    # 第二輪：找訊號
    events = []
    for t in seqs_ok:
        seq = load_ticker(main, cache, t, days)
        last_hit = {}
        for i in range(MARGIN_LOOKBACK, len(seq)):
            d, o, c, v, bal = seq[i]
            if bal is None or d < "2021-02-15":
                continue
            r20 = c / seq[i - 20][2] - 1
            if r20 > DROP_20D:
                continue
            if any(abs(seq[k][2] / seq[k - 1][2] - 1) > 0.105 for k in range(i - 19, i + 1)):
                continue
            if sum(x[3] for x in seq[i - 19:i + 1]) / 20 < MIN_AVG_VOL:
                continue
            past = [x[4] for x in seq[i - MARGIN_LOOKBACK:i + 1] if x[4] is not None]
            if len(past) < MARGIN_LOOKBACK * 0.7 or max(past) < MIN_MARGIN:
                continue
            mchg = bal / max(past) - 1
            g = next(name for name, lo, hi in GROUPS if lo < mchg <= hi or (lo == -1.0 and mchg <= hi))
            if i - last_hit.get(g, -999) < COOLDOWN:
                continue
            last_hit[g] = i
            ev = {"t": t, "d": d, "g": g, "r20": r20, "mchg": mchg, "mkt20": bmean.get(d, {}).get("r20")}
            for n in HORIZONS:
                r = fwd(seq, i, n)
                b = bmean.get(d, {}).get(n)
                ev[n] = r
                ev[f"x{n}"] = None if r is None or b is None else r - b
            events.append(ev)

    def stats(evs, label):
        out = [f"{label:<28} n={len(evs):>5}"]
        for n in HORIZONS:
            rs = [e[n] for e in evs if e[n] is not None]
            xs = [e[f"x{n}"] for e in evs if e[f"x{n}"] is not None]
            if len(rs) < 10:
                out.append(f"{n}日: 樣本不足")
                continue
            out.append(f"{n}日 均{st.mean(rs)*100:+.1f}% 中{st.median(rs)*100:+.1f}% 勝{sum(r>0 for r in rs)/len(rs)*100:.0f}% "
                       f"超額均{st.mean(xs)*100:+.1f}% 中{st.median(xs)*100:+.1f}% 贏大盤{sum(x>0 for x in xs)/len(xs)*100:.0f}%")
        print(" | ".join(out), flush=True)

    print("\n== 全部期間 ==")
    for name, *_ in GROUPS:
        stats([e for e in events if e["g"] == name], name)

    print("\n== 只看大盤也在急跌時（全市場等權 20 日跌超過 8%，像現在） ==")
    for name, *_ in GROUPS:
        stats([e for e in events if e["g"] == name and e["mkt20"] is not None and e["mkt20"] <= -0.08], name)

    print("\n== 大盤沒急跌時（個股自己崩） ==")
    for name, *_ in GROUPS:
        stats([e for e in events if e["g"] == name and e["mkt20"] is not None and e["mkt20"] > -0.08], name)

    print("\n== A 組依年份（穩不穩定） ==")
    for y in sorted({e["d"][:4] for e in events}):
        for name, *_ in GROUPS[::2]:
            stats([e for e in events if e["g"] == name and e["d"][:4] == y], f"{y} {name[:6]}")

    print("\n== A 組依跌幅深度 ==")
    for lo, hi, lab in [(-0.30, -0.20, "跌 20~30%"), (-0.40, -0.30, "跌 30~40%"), (-9, -0.40, "跌 >40%")]:
        stats([e for e in events if e["g"] == GROUPS[0][0] and lo < e["r20"] <= hi], lab)

    print("\n== A 組依融資砍幅 ==")
    for lo, hi, lab in [(-0.35, -0.25, "融資 -25~-35%"), (-0.50, -0.35, "融資 -35~-50%"), (-1, -0.50, "融資 <-50%")]:
        stats([e for e in events if e["g"] == GROUPS[0][0] and lo < e["mchg"] <= hi], lab)

    # 大盤急跌時的 A 組：扣成本後，持有 20 日的實際交易結果
    xs = [e for e in events if e["g"] == GROUPS[0][0] and e["mkt20"] is not None and e["mkt20"] <= -0.08 and e[20] is not None]
    if xs:
        net = [e[20] - COST for e in xs]
        print(f"\n大盤急跌時 A 組持有 20 日扣成本：每筆平均 {st.mean(net)*100:+.2f}%，勝率 {sum(n>0 for n in net)/len(net)*100:.0f}%，"
              f"最差 {min(net)*100:.1f}%，最好 {max(net)*100:.1f}%")
        print("各次急跌事件的 A 組（日期月份: 筆數, 20日平均, 20日超額平均）:")
        bym = defaultdict(list)
        for e in xs:
            bym[e["d"][:7]].append(e)
        for m, es in sorted(bym.items()):
            print(f"  {m}: {len(es)} 筆, {st.mean(e[20] for e in es)*100:+.1f}%, "
                  f"{st.mean(e['x20'] for e in es if e['x20'] is not None)*100:+.1f}%")


if __name__ == "__main__":
    {"fetch": fetch, "run": run}[sys.argv[1]]()
