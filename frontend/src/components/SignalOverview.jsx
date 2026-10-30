import { useState, useEffect } from "react";
import { getSignalOverview, getClaudePerformance, getPaperPerformance, getFuturesPaperPerformance } from "../api";

const pctClass = (v) => (v > 0 ? "up" : v < 0 ? "down" : "");
const renderPct = (v) => (v != null ? `${v > 0 ? "+" : ""}${v}%` : "—");

const VERDICT_CLASS = { "有效": "good", "普通": "fair", "無效": "bad", "樣本不足": "pending" };

// 各帳戶績效個別抓：自己的模擬帳戶要登入才拿得到，某一個失敗不該讓整頁都空掉
const safe = (p) => p.then((res) => res.data).catch(() => null);

export default function SignalOverview() {
  const [signals, setSignals] = useState([]);
  const [perfs, setPerfs] = useState({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    const loggedIn = !!localStorage.getItem("token");
    Promise.all([
      safe(getSignalOverview(180)),
      loggedIn ? safe(getPaperPerformance()) : null,
      loggedIn ? safe(getFuturesPaperPerformance()) : null,
      safe(getClaudePerformance("longterm")),
      safe(getClaudePerformance("shortterm")),
      safe(getClaudePerformance("daytrade")),
    ])
      .then(([sig, myStock, myFutures, lt, st, dt]) => {
        setSignals(sig?.data || []);
        setPerfs({ myStock, myFutures, lt, st, dt });
      })
      .finally(() => setLoading(false));
  }, []);

  const perfRows = [
    { label: "我的股票模擬帳戶", perf: perfs.myStock, mine: true },
    { label: "我的期貨模擬帳戶", perf: perfs.myFutures, mine: true },
    { label: "Claude 長期投資", perf: perfs.lt },
    { label: "Claude 短期交易", perf: perfs.st },
    { label: "Claude 當沖交易", perf: perfs.dt },
  ];

  // 逐月表只放算得出超額報酬的訊號，欄位是所有訊號出現過的月份聯集
  const monthlySignals = signals.filter((s) => s.monthly_excess?.length);
  const months = [...new Set(monthlySignals.flatMap((s) => s.monthly_excess.map((m) => m.month)))].sort();

  return (
    <div className="page">
      <h2>策略成績單</h2>
      <p className="ranking-hint">
        每個訊號都假設「訊號當天收盤買進，抱 N 個交易日」，再跟<b>同一天全市場平均</b>抱一樣久的報酬比較。
        「超額報酬」是訊號比大盤多賺的部分，這個才是訊號真正的價值：大盤一起漲時，隨便買也會賺錢。
        判定標準：已滿 20 日的訊號 ≥ 30 筆才判定，20 日超額報酬 ≥ +2% 為有效、≥ +0.5% 為普通、其餘為無效。
      </p>
      <p className="ranking-hint">
        注意「打贏大盤比例」：就算平均超額是正的，只要這個比例低於 50%，就代表賺錢靠的是少數大漲股。
        這種訊號不能只挑一兩檔賭，要分散買進、設好停損，讓贏家把報酬拉上來。
      </p>

      {loading ? (
        <p className="no-data">載入中...</p>
      ) : (
        <>
          <h3 className="paper-section-title">各訊號成效（近180天）</h3>
          {signals.length === 0 ? (
            <p className="no-data">目前還沒有任何訊號資料</p>
          ) : (
            <div className="ranking-table-wrap">
              <table className="result-table">
                <thead>
                  <tr>
                    <th>訊號</th><th>判定</th><th>訊號數</th><th>已滿20日</th>
                    <th>20日超額報酬</th><th>打贏大盤比例</th><th>20日勝率</th>
                    <th>20日平均報酬</th><th>20日中位數</th><th>5日平均</th><th>10日平均</th>
                  </tr>
                </thead>
                <tbody>
                  {signals.map((s) => (
                    <tr key={s.scan_type}>
                      <td className="col-ticker">{s.label}</td>
                      <td>
                        {s.verdict ? (
                          <span className={`exchange-badge verdict-badge ${VERDICT_CLASS[s.verdict]}`}>{s.verdict}</span>
                        ) : "—"}
                      </td>
                      <td>{s.count}</td>
                      <td>{s.mature_count}</td>
                      <td className={pctClass(s.excess_20d)}><b>{renderPct(s.excess_20d)}</b></td>
                      <td>{s.beat_market_rate != null ? `${s.beat_market_rate}%` : "—"}</td>
                      <td>{s.win_rate != null ? `${s.win_rate}%` : "累積中"}</td>
                      <td className={pctClass(s.avg_return_20d)}>{renderPct(s.avg_return_20d)}</td>
                      <td className={pctClass(s.median_return_20d)}>{renderPct(s.median_return_20d)}</td>
                      <td className={pctClass(s.avg_return_5d)}>{renderPct(s.avg_return_5d)}</td>
                      <td className={pctClass(s.avg_return_10d)}>{renderPct(s.avg_return_10d)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {monthlySignals.length > 0 && (
            <>
              <h3 className="paper-section-title">逐月 20 日超額報酬（依訊號發出月份）</h3>
              <p className="ranking-hint">
                看訊號是不是每個月都穩定贏大盤，還是只靠某一個月撐起來。只靠單月的訊號，換了行情很可能就失效。
                括號裡是該月的訊號筆數，筆數太少的月份參考價值低。
              </p>
              <div className="ranking-table-wrap">
                <table className="result-table">
                  <thead>
                    <tr>
                      <th>訊號</th>
                      {months.map((m) => <th key={m}>{m}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {monthlySignals.map((s) => {
                      const byMonth = Object.fromEntries(s.monthly_excess.map((m) => [m.month, m]));
                      return (
                        <tr key={s.scan_type}>
                          <td className="col-ticker">{s.label}</td>
                          {months.map((m) => (
                            <td key={m} className={pctClass(byMonth[m]?.excess_20d)}>
                              {byMonth[m] ? `${renderPct(byMonth[m].excess_20d)}（${byMonth[m].count}）` : "—"}
                            </td>
                          ))}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </>
          )}

          <h3 className="paper-section-title">模擬帳戶實際績效</h3>
          <p className="ranking-hint">
            實際模擬下單、有算手續費和稅的結果。勝率低不一定是壞事，要一起看「損益比」：
            平均獲利遠大於平均虧損，勝率低也能賺錢；損益比接近 1 又頻繁交易，手續費會慢慢把本金吃掉。
          </p>
          <div className="ranking-table-wrap">
            <table className="result-table">
              <thead>
                <tr>
                  <th>帳戶</th><th>已平倉次數</th><th>勝率</th>
                  <th>平均獲利</th><th>平均虧損</th><th>損益比</th><th>累計已實現損益</th>
                </tr>
              </thead>
              <tbody>
                {perfRows.map(({ label, perf, mine }) => (
                  <tr key={label}>
                    <td className="col-ticker">{label}</td>
                    {!perf || perf.total_trades === 0 ? (
                      <td colSpan={6} className="no-data">{perf ? "尚無已平倉交易" : mine ? "登入後才看得到" : "讀取失敗"}</td>
                    ) : (
                      <>
                        <td>{perf.total_trades}（{perf.win_count}勝{perf.loss_count}敗）</td>
                        <td>{perf.win_rate}%</td>
                        <td className="up">{perf.avg_win != null ? perf.avg_win.toLocaleString() : "—"}</td>
                        <td className="down">{perf.avg_loss != null ? perf.avg_loss.toLocaleString() : "—"}</td>
                        <td>{perf.profit_factor ?? "—"}</td>
                        <td className={pctClass(perf.total_realized_pl)}>{perf.total_realized_pl.toLocaleString()}</td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
