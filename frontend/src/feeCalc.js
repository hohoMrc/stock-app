// 台股現股手續費／證交稅試算（比照 backend/app/services/paper_trading.py 的公式）
export const COMMISSION_RATE = 0.001425;
export const COMMISSION_MIN  = 20;
export const TAX_RATE        = 0.003;

export const calcFee = (amount) => Math.max(Math.round(amount * COMMISSION_RATE), COMMISSION_MIN);
export const calcTax = (amount) => Math.round(amount * TAX_RATE);
