import os
from groq import Groq


def analyze_stock(stock_info: dict, history: list) -> str:
    """用 Groq (llama) 分析個股並給出觀點"""
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    recent = history[-20:] if len(history) >= 20 else history
    price_trend = _summarize_trend(recent)

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

請提供：
1. **技術面分析**：近期股價趨勢評估
2. **基本面評估**：估值是否合理
3. **風險提示**：投資此股需注意的風險
4. **操作建議**：偏多、偏空、還是觀望

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
