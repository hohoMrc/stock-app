// K線圖的歷史資料在後端有快取，可能比即時報價舊；用最新報價/分鐘K棒校正最後幾根，
// 讓「個股查詢」跟「看盤」用同一套規則，兩邊看到的K線才會一致。

// 日K：把最後一根棒校正成即時值（開高低收用今天的報價，收盤價用最新成交價）。
export function mergeLiveBar(historyArr, info, interval) {
  if (interval !== "1d" || !info?.quote_date || !info.open || !info.price) return historyArr;
  if (!historyArr || historyArr.length === 0) return historyArr;
  const newBar = {
    date: info.quote_date, open: info.open,
    high: info.high ?? info.price, low: info.low ?? info.price,
    close: info.price, volume: info.volume ?? 0,
  };
  const last = historyArr[historyArr.length - 1];
  if (last.date === newBar.date) return [...historyArr.slice(0, -1), newBar];
  if (newBar.date > last.date) return [...historyArr, newBar];
  return historyArr;
}

// 15分K/60分K：今天的棒直接整批換成 Fugle 即時分鐘K棒（比 yfinance 準且沒有快取延遲），
// 較早之前幾天的棒維持原本 yfinance 資料，用時間戳比對切開，不用管兩邊分桶邊界是否對齊。
export function mergeIntradayBars(historyArr, todayCandles) {
  if (!todayCandles || todayCandles.length === 0) return historyArr;
  const cutoff = todayCandles[0].date;
  const past = (historyArr || []).filter((r) => r.date < cutoff);
  return [...past, ...todayCandles];
}
