import os
from groq import Groq


def analyze_stock(stock_info: dict, history: list, signals: dict | None = None) -> str:
    """用 Groq (llama) 分析個股並給出觀點"""
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    recent = history[-20:] if len(history) >= 20 else history
    price_trend = _summarize_trend(recent)
    signals_section = _summarize_signals(signals) if signals else ""

    prompt = f"""你是一位台股投資分析師，請根據以下資料分析這支股票，給出客觀的投資觀點。

## 股票基本資料
- 股票代號：{stock_info.get('ticker')}
- 公司名稱：{stock_info.get('name')}
- 目前股價：{stock_info.get('price')} 元
- 本益比 (PE)：{stock_info.get('pe_ratio')}
- 股價淨值比 (PB)：{stock_info.get('pb_ratio')}
- 殖利率：{stock_info.get('dividend_yield')}%
- 產業：{stock_info.get('industry')}
- 52週高點：{stock_info.get('week_52_high')}
- 52週低點：{stock_info.get('week_52_low')}

## 近期走勢
{price_trend}
{signals_section}
請提供：
1. **技術面分析**：近期股價趨勢評估，並說明是否有命中上述技術訊號、三關價支撐壓力對後市的意義
2. **籌碼面評估**：三大法人買賣超狀況代表的意義
3. **基本面評估**：估值是否合理
4. **風險提示**：投資此股需注意的風險
5. **操作建議**：偏多、偏空、還是觀望

注意：這只是分析參考，不構成投資建議。"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    return response.choices[0].message.content


def _summarize_trend(history: list[dict]) -> str:
    if not history:
        return "無資料"

    first = history[0]
    last = history[-1]
    change = ((last["close"] - first["close"]) / first["close"]) * 100

    return (
        f"近 {len(history)} 個交易日：從 {first['close']} 元 → {last['close']} 元，"
        f"漲跌幅 {change:+.2f}%\n"
        f"最高：{max(d['high'] for d in history)} 元，"
        f"最低：{min(d['low'] for d in history)} 元"
    )


def _summarize_signals(signals: dict) -> str:
    parts = []

    hits = signals.get("scan_hits") or []
    parts.append(
        "\n## 技術面掃描訊號\n"
        + ("目前命中：" + "；".join(hits) if hits else "目前未命中任何內建掃描條件（鳥嘴與分歧/EMA60近線/量價突破/法人連買）")
    )

    gates = signals.get("gates")
    if gates:
        parts.append(
            "\n## 三關價（用前一交易日高低價算出的支撐壓力參考）\n"
            f"上關：{gates['upper']} 元／中關：{gates['mid']} 元／下關：{gates['lower']} 元"
        )

    recent = signals.get("institutional_recent") or []
    streak = signals.get("institutional_streak_days", 0)
    if recent:
        lines = "\n".join(
            f"{r['date']}：外資 {r['foreign_net']:+} 張、投信 {r['trust_net']:+} 張、自營商 {r['dealer_net']:+} 張"
            for r in recent
        )
        streak_note = f"（外資+投信目前連續買超 {streak} 天）" if streak >= 3 else ""
        parts.append(f"\n## 三大法人買賣超（近{len(recent)}個交易日，張）{streak_note}\n{lines}")

    return "\n".join(parts) + "\n"
