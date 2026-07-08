/**
 * 台股現貨交易時段（台北時間 09:00–13:30，週一至週五）
 */
export function isTradingHours() {
  const now = new Date();
  const tw  = new Date(now.toLocaleString("en-US", { timeZone: "Asia/Taipei" }));
  const day  = tw.getDay();
  if (day === 0 || day === 6) return false;
  const mins = tw.getHours() * 60 + tw.getMinutes();
  return mins >= 9 * 60 && mins <= 13 * 60 + 30;
}

/**
 * 台指期交易時段（早盤 08:45–13:45 + 下午盤 15:00–隔日05:00，週一至週六早）
 * 週六 05:00 收盤；週日全天不交易。
 */
export function isFuturesTradingHours() {
  const now = new Date();
  const tw  = new Date(now.toLocaleString("en-US", { timeZone: "Asia/Taipei" }));
  const day  = tw.getDay();   // 0=日, 6=六
  if (day === 0) return false;
  const mins = tw.getHours() * 60 + tw.getMinutes();
  // 週六只有凌晨到 05:00（跨日夜盤尾段）
  if (day === 6) return mins < 5 * 60;
  // 週一–週五：早盤 08:45–13:45 或下午盤 15:00–24:00+（跨日到 05:00 由隔天判斷）
  return (mins >= 8 * 60 + 45 && mins <= 13 * 60 + 45) || mins >= 15 * 60;
}
