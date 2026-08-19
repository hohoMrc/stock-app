import os
from groq import Groq


def build_stock_watch(news_items: list[dict], limit: int = 15) -> list[dict]:
    """直接用鉅亨網新聞自帶的關聯個股（market欄位）彙整台股觀察清單，
    不用AI猜——比較準，也不用花Groq額度。news_items已依時間新到舊排序，
    同一檔股票重複出現時保留最新那則新聞的標題。
    """
    seen = set()
    watch = []
    for n in news_items:
        for s in n.get("stocks") or []:
            code = s["code"]
            if code in seen:
                continue
            seen.add(code)
            watch.append({
                "code": code, "name": s["name"],
                "headline": n["title"], "link": n["link"], "tag": n.get("tag"),
            })
            if len(watch) >= limit:
                return watch
    return watch


def summarize_news(news_items: list[dict]) -> str:
    """用 Groq (gpt-oss) 整理今日財經新聞重點（純文字摘要）。
    個股清單改用 build_stock_watch() 直接從新聞自帶的關聯個股欄位產生，不用AI猜，
    這裡只需要負責把當天的新聞脈絡整理成幾點重點。
    """
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    titles = "\n".join(
        f"{i + 1}. {n['title']}" for i, n in enumerate(news_items)
    )

    prompt = f"""你是一位台股投資分析師，請根據以下今日台股新聞標題，整理今天的重點，
讓沒時間細讀每則新聞的人也能快速掌握狀況。

## 今日台股新聞標題
{titles}

請條列整理今天最重要的財經/產業/大盤動態在說什麼，合併相似主題、不用每則都列，
只抓真正重要的3-6點，個股層級的細節（例如個別公司營收）不用在這裡重複列，
那些已經有另外的個股清單呈現。

格式要求：純文字條列，每點一行、不超過50字，不要用表格、不要有子項目或總結段落，
這是要塞進Telegram訊息的，越精簡越好。

注意：這只是新聞整理參考，不構成投資建議。"""

    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        max_tokens=1024,
        temperature=0.3,
        reasoning_effort="low",
        messages=[{"role": "user", "content": prompt}],
    )

    return response.choices[0].message.content
