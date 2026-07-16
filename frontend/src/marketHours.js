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
 * 台指期日盤交易時段（08:45–13:45，週一至週五）。
 */
export function isDaySessionHours() {
  const now = new Date();
  const tw  = new Date(now.toLocaleString("en-US", { timeZone: "Asia/Taipei" }));
  const day  = tw.getDay();
  if (day === 0 || day === 6) return false;
  const mins = tw.getHours() * 60 + tw.getMinutes();
  return mins >= 8 * 60 + 45 && mins <= 13 * 60 + 45;
}

/**
 * 台指期夜盤交易時段（15:00–隔日05:00）。
 * 週一到週五 15:00 之後算當晚開始；週二到週六 05:00 前算前一晚延續
 * （週一凌晨屬於週日，週日不開盤所以不算）。
 */
export function isNightSessionHours() {
  const now = new Date();
  const tw  = new Date(now.toLocaleString("en-US", { timeZone: "Asia/Taipei" }));
  const day  = tw.getDay();   // 0=日 1=一 ... 6=六
  const mins = tw.getHours() * 60 + tw.getMinutes();
  if (day >= 1 && day <= 5 && mins >= 15 * 60) return true;
  if (day >= 2 && day <= 6 && mins < 5 * 60) return true;
  return false;
}

/**
 * 台指期日盤或夜盤任一時段正在交易中。
 */
export function isFuturesTradingHours() {
  return isDaySessionHours() || isNightSessionHours();
}
