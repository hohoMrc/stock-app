import os
from groq import Groq


def summarize_news(news_items: list[dict]) -> str:
    """用 Groq (llama) 整理當日財經新聞重點跟台股觀察，供每日新聞通知/網頁摘要用。
    找個股優先根據「熱門新聞」（hot_score>=2，多家來源同時報導），
    因為那些比較可能是真的會動到股價的事件，不是單一媒體的雜訊。
    """
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    hot_items   = [n for n in news_items if n.get("hot_score", 1) >= 2]
    other_items = [n for n in news_items if n.get("hot_score", 1) < 2]

    def _fmt(items, offset=0):
        return "\n".join(f"{i + 1 + offset}. {n['title']}（{n['source']}）" for i, n in enumerate(items))

    if hot_items:
        news_section = (
            "## 熱門新聞（多家媒體同時報導同一件事，代表性較高，找個股請優先根據這些）\n"
            f"{_fmt(hot_items)}\n\n"
            "## 其他新聞（單一來源，熱門新聞裡找不到明確關聯個股時才參考這裡）\n"
            f"{_fmt(other_items, len(hot_items))}"
        )
    else:
        news_section = (
            "## 今日財經新聞（今天沒有被多家媒體同時報導的新聞，以下全部是一般新聞）\n"
            f"{_fmt(other_items)}"
        )

    prompt = f"""你是一位台股投資分析師，請根據以下今日財經新聞標題，幫我整理重點跟台股觀察，
讓沒時間細讀每則新聞的人也能快速掌握狀況。

{news_section}

請提供：
1. **今日重點**：條列整理今天最重要的財經/產業新聞在說什麼，合併相似主題、不用每則都列，
   優先取材自熱門新聞（多家媒體都報的比較重要），只抓真正重要的3-6點
2. **台股觀察**：直接條列值得留意的「個股」，**優先根據「熱門新聞」去找關聯個股**，只有
   熱門新聞裡真的找不到明確關聯個股，才退一步從其他新聞裡找。兩種關聯方式都要找：
   (a) 新聞標題裡本來就直接點名的上市櫃公司（例如營收公告、財報、被提及的個股），這些
       一定要列出來，不要因為看起來不重要就漏掉；
   (b) 新聞主題明顯會帶動的相關個股（例如某產業政策/需求消息，會受惠或受害的具體公司）。
   每一檔都必須「獨立一行」，嚴格照這個格式寫，不要換成別的寫法：
   - 名稱(代號)：正面/負面 — 一句話原因
   不確定代號就把「(代號)」整段拿掉、只留名稱，但**不要因為不知道代號就整檔跳過不提**，
   也不要用「XX類股」「XX等公司」這種籠統寫法取代逐檔列出。
   只有完全找不到任何可以點名的公司時，才退而求其次改講產業類股。

注意：這只是新聞整理參考，不構成投資建議；個股僅為新聞關聯推測，正確性請自行查證。"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=1024,
        temperature=0.3,
        messages=[{"role": "user", "content": prompt}],
    )

    return response.choices[0].message.content
