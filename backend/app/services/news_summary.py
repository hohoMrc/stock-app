import os
from groq import Groq


def summarize_news(news_items: list[dict]) -> str:
    """用 Groq (llama) 整理當日財經新聞重點跟台股觀察，供每日新聞通知/網頁摘要用。"""
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    titles = "\n".join(
        f"{i + 1}. {n['title']}（{n['source']}）" for i, n in enumerate(news_items)
    )

    prompt = f"""你是一位台股投資分析師，請根據以下今日財經新聞標題，幫我整理重點跟台股觀察，
讓沒時間細讀每則新聞的人也能快速掌握狀況。

## 今日財經新聞標題
{titles}

請提供：
1. **今日重點**：條列整理今天最重要的財經/產業新聞在說什麼，合併相似主題、不用每則都列，
   只抓真正重要的3-6點
2. **台股觀察**：這些新聞可能對台股哪些類股或個股有正面/負面影響，值得留意什麼

注意：這只是新聞整理參考，不構成投資建議。"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    return response.choices[0].message.content
