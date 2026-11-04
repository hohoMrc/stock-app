// 外部監控：每 5 分鐘從 Cloudflare 機房檢查家用主機上的後端 API，狀態改變（斷線／恢復）才發 Telegram。
// 跑在 Cloudflare 上而不是家用主機：主機自己斷網時，主機上的排程連通知都發不出去（2026-10-12 就斷了 3 小時沒人發現）。

const FAIL_THRESHOLD = 2; // 連續失敗 2 次（約 10 分鐘）才算斷線，避免偶發逾時誤報

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(check(env));
  },
};

async function probe(url) {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(15000) });
    return res.ok ? null : `HTTP ${res.status}`;
  } catch (e) {
    return String(e).slice(0, 100);
  }
}

async function check(env) {
  const err = await probe(env.TARGET_URL);
  const prev = JSON.parse((await env.STATE.get("state")) || '{"down":false,"fails":0}');
  const now = new Date().toLocaleString("zh-TW", { timeZone: "Asia/Taipei", hour12: false });

  if (err) {
    const fails = prev.fails + 1;
    if (!prev.down && fails >= FAIL_THRESHOLD) {
      await notify(env,
        `🔴 [主機監控] stock-api 連不上（${now}，已連續 ${fails} 次）\n原因：${err}\n` +
        `可能是家裡斷網、主機當機或 Cloudflare Tunnel 中斷；這段期間主機上的排程與 TG 通知都不會運作。`);
      await env.STATE.put("state", JSON.stringify({ down: true, fails, since: now }));
    } else if (!prev.down) {
      // 只記錄未達門檻的失敗次數；已經在斷線狀態就不再寫入（KV 免費額度每天只有 1000 次寫入）
      await env.STATE.put("state", JSON.stringify({ down: false, fails }));
    }
  } else if (prev.down) {
    await notify(env, `🟢 [主機監控] stock-api 已恢復（${now}），從 ${prev.since} 起斷線`);
    await env.STATE.put("state", JSON.stringify({ down: false, fails: 0 }));
  } else if (prev.fails) {
    await env.STATE.put("state", JSON.stringify({ down: false, fails: 0 }));
  }
}

async function notify(env, text) {
  const res = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ chat_id: env.TELEGRAM_CHAT_ID, text }),
  });
  if (!res.ok) console.log("Telegram 通知失敗", res.status, await res.text());
}
