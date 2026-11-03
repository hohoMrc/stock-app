"""
開盤當沖回測：用 Fugle 歷史 1 分 K，比較不同的進場（選股）與出場規則，
找出 Claude 當沖帳戶該怎麼改。現行規則（追成交值前 30 名、漲 4~9% 的股票）在實盤虧損。

用法：
  python3 scripts/backtest_daytrade.py fetch   # 抓分K存進 backtest_cache.db（已抓過的會跳過，可中斷續抓）
  python3 scripts/backtest_daytrade.py run     # 跑全部策略組合，印出樣本內／樣本外成績

設計重點：
- 股票池：每天取「前一個交易日」成交值前 100 名（不用當天資料，避免偷看答案）
- 樣本內 START~SPLIT 用來挑參數，樣本外 SPLIT~END 用來驗證，避免過度擬合
- 成本：手續費 0.1425%×2、當沖證交稅 0.15%，每邊再加 0.05% 滑價
- 13:25 強制平倉用 13:30 收盤價：台股 13:25~13:30 是收盤集合競價，這時下的單實際用收盤價成交
- 同一根 K 棒同時碰到停損和停利時，保守當作先停損
"""
import os
import sqlite3
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

BACKEND = os.path.join(os.path.dirname(__file__), "..")
MAIN_DB = os.path.join(BACKEND, "stock_cache.db")
CACHE_DB = os.path.join(BACKEND, "backtest_cache.db")

START, SPLIT, END = "2025-11-03", "2026-07-01", "2026-10-30"
UNIVERSE_SIZE = 100

COMMISSION = 0.001425
DAY_TRADE_TAX = 0.0015
SLIPPAGE = 0.0005

OPEN_MIN = 9 * 60           # 09:00 = 分K索引 0
LAST_IDX = 270              # 13:30 收盤那根
ENTRY_CUTOFF_IDX = 210      # 12:30 之後不再進場（同現行規則）
MAX_POSITIONS = 5


# ── 資料準備 ─────────────────────────────────────────────────

def trading_days(main) -> list[str]:
    # 全市場超過 1000 檔有日K的日子才算交易日（排除零星補資料的日期）
    return [r[0] for r in main.execute(
        "SELECT date FROM candles GROUP BY date HAVING COUNT(*) > 1000 ORDER BY date")]


def build_universe(main) -> dict[str, list[str]]:
    """{交易日: 前一交易日成交值前 N 名}"""
    days = trading_days(main)
    uni = {}
    for prev, day in zip(days, days[1:]):
        if not (START <= day <= END):
            continue
        uni[day] = [r[0] for r in main.execute(
            "SELECT ticker FROM candles WHERE date=? AND close>0 "
            "ORDER BY close*volume DESC LIMIT ?", (prev, UNIVERSE_SIZE))]
    return uni


def open_cache():
    c = sqlite3.connect(CACHE_DB)
    c.executescript("""
        CREATE TABLE IF NOT EXISTS bars (
            ticker TEXT, day TEXT, idx INTEGER,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER,
            PRIMARY KEY (ticker, day, idx)
        );
        CREATE INDEX IF NOT EXISTS idx_bars_day ON bars(day, ticker);
        CREATE TABLE IF NOT EXISTS fetched (ticker TEXT PRIMARY KEY);
    """)
    return c


def fetch():
    from app.services.stock_data import _call_fugle, shutdown_fugle
    main = sqlite3.connect(MAIN_DB)
    cache = open_cache()
    uni = build_universe(main)
    need = defaultdict(set)   # ticker → 需要的交易日
    for day, tickers in uni.items():
        for t in tickers:
            need[t].add(day)
    done = {r[0] for r in cache.execute("SELECT ticker FROM fetched")}
    todo = sorted(t for t in need if t not in done)
    print(f"[fetch] 交易日 {len(uni)} 天，股票池聯集 {len(need)} 檔，待抓 {len(todo)} 檔")

    # Fugle 一次最多抓約半年的 1 分K，分兩段
    chunks = [(START, "2026-04-30"), ("2026-05-01", END)]
    for i, t in enumerate(todo, 1):
        rows = []
        for f, to in chunks:
            for attempt in range(3):
                try:
                    resp = _call_fugle(lambda c: c.stock.historical.candles(
                        symbol=t, timeframe="1", **{"from": f, "to": to}))
                    break
                except Exception as e:
                    if "429" in str(e) or "Rate limit" in str(e):
                        time.sleep(30 * (attempt + 1))
                        continue
                    print(f"  ✗ {t} {f}~{to}: {str(e)[:80]}")
                    resp = {}
                    break
            for b in (resp.get("data", []) if isinstance(resp, dict) else []):
                day = b["date"][:10]
                if day not in need[t]:
                    continue
                hh, mm = int(b["date"][11:13]), int(b["date"][14:16])
                idx = hh * 60 + mm - OPEN_MIN
                if 0 <= idx <= LAST_IDX:
                    rows.append((t, day, idx, b["open"], b["high"], b["low"], b["close"], b.get("volume") or 0))
            time.sleep(0.7)   # Fugle 限制每分鐘 100 次
        cache.executemany("INSERT OR REPLACE INTO bars VALUES (?,?,?,?,?,?,?,?)", rows)
        cache.execute("INSERT OR REPLACE INTO fetched VALUES (?)", (t,))
        cache.commit()
        if i % 20 == 0:
            print(f"  進度 {i}/{len(todo)}")
    shutdown_fugle()
    print("[fetch] 完成")


# ── 回測引擎 ─────────────────────────────────────────────────

def tick_floor(price: float) -> float:
    """台股升降單位往下取整，用來算漲停價。"""
    for limit, tick in ((10, 0.01), (50, 0.05), (100, 0.1), (500, 0.5), (1000, 1)):
        if price < limit:
            return round(int(price / tick + 1e-9) * tick, 2)
    return int(price / 5 + 1e-9) * 5


def load_day(main, cache, day: str, tickers: list[str]) -> dict:
    """回傳 {ticker: 這天的分K陣列與衍生指標}，缺的分鐘用前一根收盤補（量 0）。"""
    prev = main.execute("SELECT MAX(date) FROM candles WHERE date<? AND ticker='2330'", (day,)).fetchone()[0]
    out = {}
    ph = ",".join("?" * len(tickers))
    raw = defaultdict(dict)
    for t, idx, o, h, l, c, v in cache.execute(
            f"SELECT ticker, idx, open, high, low, close, volume FROM bars WHERE day=? AND ticker IN ({ph})",
            (day, *tickers)):
        raw[t][idx] = (o, h, l, c, v)
    for t in tickers:
        bars = raw.get(t)
        if not bars or 0 not in bars:
            continue
        pc = main.execute("SELECT close FROM candles WHERE ticker=? AND date=?", (t, prev)).fetchone()
        vols = [r[0] for r in main.execute(
            "SELECT volume FROM candles WHERE ticker=? AND date<=? ORDER BY date DESC LIMIT 5", (t, prev))]
        if not pc or not pc[0] or not vols:
            continue
        o, h, l, c, v = [], [], [], [], []
        last = bars[0][3]
        for i in range(LAST_IDX + 1):
            b = bars.get(i)
            if b:
                o.append(b[0]); h.append(b[1]); l.append(b[2]); c.append(b[3]); v.append(b[4])
                last = b[3]
            else:
                o.append(last); h.append(last); l.append(last); c.append(last); v.append(0)
        cum_val, cum_vol, vwap, cv, cvol = [], [], [], 0.0, 0
        for i in range(LAST_IDX + 1):
            cv += c[i] * v[i]
            cvol += v[i]
            cum_val.append(cv)
            cum_vol.append(cvol)
            vwap.append(cv / cvol if cvol else c[i])
        out[t] = {
            "o": o, "h": h, "l": l, "c": c, "cum_val": cum_val, "cum_vol": cum_vol, "vwap": vwap,
            "prev_close": pc[0], "limit_up": tick_floor(pc[0] * 1.1),
            # 1 分K 量單位是張、DB 日K 量是股
            "avg_daily_lots": sum(vols) / len(vols) / 1000,
            "or_high": max(h[:5]), "or_low": min(l[:5]),
        }
    return out


def simulate_exit(d: dict, entry_idx: int, entry_px: float, ex: dict, stop_px: float):
    """從進場後下一根開始逐分鐘檢查出場，回傳 (出場索引, 出場價, 出場原因)。"""
    peak = entry_px
    for i in range(entry_idx + 1, LAST_IDX + 1):
        o, h, l, c = d["o"][i], d["h"][i], d["l"][i], d["c"][i]
        if i == LAST_IDX:
            return i, c, "收盤平倉"
        if l <= stop_px:
            return i, min(stop_px, o), "停損"
        if h >= d["limit_up"]:
            return i, d["limit_up"], "觸及漲停"
        if ex["take"][0] == "target" and h >= entry_px * (1 + ex["take"][1] / 100):
            return i, max(entry_px * (1 + ex["take"][1] / 100), o), "停利"
        peak = max(peak, h)
        if ex["take"][0] == "trail":
            trig, retrace = ex["take"][1], ex["take"][2]
            peak_ret = (peak / entry_px - 1) * 100
            cur_ret = (c / entry_px - 1) * 100
            if peak_ret >= trig and peak_ret - cur_ret >= retrace:
                return i, c, "移動停利"
        if ex["time"] and i - entry_idx >= ex["time"] and (c / entry_px - 1) * 100 < 0.5:
            return i, c, "時間停損"
    return LAST_IDX, d["c"][LAST_IDX], "收盤平倉"


def entry_candidates(strategy: str, day_data: dict, idx: int, rank: list[str], params: dict) -> list[str]:
    """回傳這一分鐘符合進場條件的股票（依優先順序）。"""
    out = []
    if strategy == "S0":
        # 現行規則：每 2 分鐘檢查，當下成交值前 30 名、漲幅 4~9%、沒漲停
        if idx % 2 or idx > ENTRY_CUTOFF_IDX:
            return []
        for t in rank[:30]:
            d = day_data[t]
            chg = (d["c"][idx] / d["prev_close"] - 1) * 100
            if 4 <= chg <= 9 and d["c"][idx] < d["limit_up"]:
                out.append(t)
        return out

    # S1~S3 只在 09:05~10:00 進場，池子是 09:04 時成交值前 30 名
    if not (5 <= idx <= 60):
        return []
    for t in rank[:30]:
        d = day_data[t]
        c, pc = d["c"][idx], d["prev_close"]
        chg = (c / pc - 1) * 100
        if not (1 <= chg <= 7) or c <= d["vwap"][idx] or c >= d["limit_up"]:
            continue
        vol_ratio = d["cum_vol"][4] / d["avg_daily_lots"] if d["avg_daily_lots"] else 0
        breakout = c > d["or_high"] and d["c"][idx - 1] <= d["or_high"]
        or_range = (d["or_high"] - d["or_low"]) / pc * 100
        if strategy == "S1":
            ok = breakout and or_range <= 4
        elif strategy == "S2":
            ok = vol_ratio >= params["vol_ratio"] and c > d["o"][0]
        else:  # S3
            ok = breakout and or_range <= 4 and vol_ratio >= params["vol_ratio"]
        if ok:
            out.append(t)
    return out


def run_day(day_data: dict, strategy: str, ex: dict, params: dict) -> list[dict]:
    if not day_data:
        return []
    trades, open_until, traded = [], [], set()
    rank_fixed = sorted(day_data, key=lambda t: day_data[t]["cum_val"][4], reverse=True)
    for idx in range(0, ENTRY_CUTOFF_IDX + 1):
        if strategy == "S0":
            rank = sorted(day_data, key=lambda t: day_data[t]["cum_val"][idx], reverse=True) if idx % 2 == 0 else []
        else:
            rank = rank_fixed
        if not rank:
            continue
        for t in entry_candidates(strategy, day_data, idx, rank, params):
            open_until = [e for e in open_until if e > idx]
            if len(open_until) >= MAX_POSITIONS:
                break
            if t in traded:
                continue
            d = day_data[t]
            entry_px = d["c"][idx] * (1 + SLIPPAGE)
            if ex["stop"] == "or_low":
                # 結構停損：開盤區間低點，但最多賠 3%、最少留 0.5% 空間
                stop_px = max(min(d["or_low"], entry_px * 0.995), entry_px * 0.97)
            else:
                stop_px = entry_px * (1 + ex["stop"] / 100)
            exit_idx, exit_px, reason = simulate_exit(d, idx, entry_px, ex, stop_px)
            exit_px *= (1 - SLIPPAGE)
            net = exit_px * (1 - COMMISSION - DAY_TRADE_TAX) / (entry_px * (1 + COMMISSION)) - 1
            trades.append({"ticker": t, "entry_idx": idx, "hold": exit_idx - idx, "reason": reason, "net": net * 100})
            traded.add(t)
            open_until.append(exit_idx)
    return trades


def summarize(trades: list[dict]) -> dict:
    n = len(trades)
    if not n:
        return {"n": 0}
    wins = [t["net"] for t in trades if t["net"] > 0]
    losses = [t["net"] for t in trades if t["net"] <= 0]
    return {
        "n": n,
        "win": len(wins) / n * 100,
        "avg": sum(t["net"] for t in trades) / n,
        "avg_win": sum(wins) / len(wins) if wins else 0,
        "avg_loss": sum(losses) / len(losses) if losses else 0,
        "total": sum(t["net"] for t in trades),
    }


def fmt(s: dict) -> str:
    if not s["n"]:
        return "（無交易）"
    return (f"{s['n']:>4}筆 勝率{s['win']:5.1f}% 平均{s['avg']:+.2f}% "
            f"(賺{s['avg_win']:+.2f}/賠{s['avg_loss']:+.2f}) 累計{s['total']:+7.1f}%")


def run():
    main = sqlite3.connect(MAIN_DB)
    cache = open_cache()
    uni = build_universe(main)

    takes = [("trail", 3, 1.5), ("trail", 2, 1), ("target", 2)]
    configs = [("S0", {"stop": -5, "take": ("trail", 3, 1.5), "time": None}, {})]   # 現行規則
    for stop in (-2, -3, -5):
        for take in takes:
            for tm in (None, 30):
                configs.append(("S0", {"stop": stop, "take": take, "time": tm}, {}))
    # 開盤 5 分鐘量 ÷ 近 5 日日均量：實測中位數約 7.7%、前 25% 約 10%、前 10% 約 14%，
    # 門檻要明顯高於常態才算「爆量」，測 12% 與 20% 兩檔（S1 不看量，只跑一次）
    for strat in ("S1", "S2", "S3"):
        for vol_ratio in ((None,) if strat == "S1" else (0.12, 0.20)):
            for stop in (-2, -3, "or_low"):
                for take in takes:
                    for tm in (None, 30):
                        configs.append((strat, {"stop": stop, "take": take, "time": tm}, {"vol_ratio": vol_ratio}))

    results = defaultdict(lambda: {"in": [], "out": [], "by_month": defaultdict(list)})
    days = sorted(uni)
    for n_day, day in enumerate(days, 1):
        day_data = load_day(main, cache, day, uni[day])
        for i, (strat, ex, params) in enumerate(configs):
            tr = run_day(day_data, strat, ex, params)
            r = results[i]
            (r["in"] if day < SPLIT else r["out"]).extend(tr)
            r["by_month"][day[:7]].extend(tr)
        if n_day % 20 == 0:
            print(f"  已跑 {n_day}/{len(days)} 天", flush=True)

    def label(strat, ex, params):
        take = ex["take"]
        take_s = f"移動停利{take[1]}/{take[2]}" if take[0] == "trail" else f"停利+{take[1]}%"
        stop_s = "停損開盤區間低" if ex["stop"] == "or_low" else f"停損{ex['stop']}%"
        vol_s = f" 量比≥{int(params['vol_ratio'] * 100)}%" if params.get("vol_ratio") else ""
        return f"{strat}{vol_s} {stop_s} {take_s}{' 時間停損30分' if ex['time'] else ''}"

    rows = []
    for i, (strat, ex, params) in enumerate(configs):
        rows.append((label(strat, ex, params), summarize(results[i]["in"]), summarize(results[i]["out"]), i))

    print(f"\n股票池：每天前一交易日成交值前 {UNIVERSE_SIZE} 名；樣本內 {START}~{SPLIT}，樣本外 {SPLIT}~{END}")
    print("\n== 現行規則（基準）==")
    print(rows[0][0], "\n  樣本內", fmt(rows[0][1]), "\n  樣本外", fmt(rows[0][2]))

    print("\n== 各進場方式在樣本內最好的 3 組，與它們的樣本外成績 ==")
    for strat in ("S0", "S1", "S2", "S3"):
        cand = [r for r in rows[1:] if r[0].startswith(strat) and r[1]["n"] >= 30]
        cand.sort(key=lambda r: r[1]["avg"], reverse=True)
        for lbl, s_in, s_out, _ in cand[:3]:
            print(lbl, "\n  樣本內", fmt(s_in), "\n  樣本外", fmt(s_out))

    best = max((r for r in rows[1:] if r[1]["n"] >= 30), key=lambda r: r[1]["avg"])
    print(f"\n== 樣本內最佳組合逐月：{best[0]} ==")
    for m, tr in sorted(results[best[3]]["by_month"].items()):
        print(m, fmt(summarize(tr)))
    reasons = defaultdict(list)
    for t in results[best[3]]["in"] + results[best[3]]["out"]:
        reasons[t["reason"]].append(t)
    print("出場原因：", {k: f"{len(v)}筆 平均{sum(x['net'] for x in v) / len(v):+.2f}%" for k, v in reasons.items()})


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "fetch":
        fetch()
    elif cmd == "run":
        run()
    else:
        print(__doc__)
