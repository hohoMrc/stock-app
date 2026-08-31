import { useState, useEffect } from "react";
import { getSignalOverview, getClaudePerformance } from "../api";

const pctClass = (v) => (v > 0 ? "up" : v < 0 ? "down" : "");
const renderPct = (v) => (v != null ? `${v > 0 ? "+" : ""}${v}%` : "—");

export default function SignalOverview() {
  const [signals, setSignals] = useState([]);
  const [ltPerf, setLtPerf] = useState(null);
  const [stPerf, setStPerf] = useState(null);
  const [dtPerf, setDtPerf] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      getSignalOverview(180),
      getClaudePerformance("longterm"),
      getClaudePerformance("shortterm"),
      getClaudePerformance("daytrade"),
    ])
      .then(([sRes, ltRes, stRes, dtRes]) => {
        setSignals(sRes.data.data || []);
        setLtPerf(ltRes.data);
        setStPerf(stRes.data);
        setDtPerf(dtRes.data);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const perfRows = [
    { label: "Claude 長期投資", perf: ltPerf },
    { label: "Claude 短期交易", perf: stPerf },
    { label: "Claude 當沖交易", perf: dtPerf },
  ];

  return (
    <div className="page">
      <h2>訊號績效總覽</h2>
      <p className="ranking-hint">
        統整所有掃描訊號/技術指標的追蹤成效，方便一眼比較哪些真的有用。5/10/20日報酬率是
        「如果訊號當天用收盤價買進，之後N個交易日的報酬率」，是假設性的參考數字，不是真的
        下單的結果；還沒滿20個交易日的訊號會先顯示「累積中」，5/10日的部分平均值會隨時間
        陸續補上。下面的 Claude 帳戶績效才是實際模擬交易、有真的算手續費/稅的結果。
      </p>

      {loading ? (
        <p className="no-data">載入中...</p>
      ) : (
        <>
          <h3 className="paper-section-title">各訊號來源成效（近180天）</h3>
          {signals.length === 0 ? (
            <p className="no-data">目前還沒有任何訊號資料</p>
          ) : (
            <div className="ranking-table-wrap">
              <table className="result-table">
                <thead>
                  <tr>
                    <th>訊號</th><th>訊號數</th><th>已滿20日</th><th>20日勝率</th>
                    <th>5日平均報酬</th><th>10日平均報酬</th><th>20日平均報酬</th>
                  </tr>
                </thead>
                <tbody>
                  {signals.map((s) => (
                    <tr key={s.scan_type}>
                      <td className="col-ticker">{s.label}</td>
                      <td>{s.count}</td>
                      <td>{s.mature_count}</td>
                      <td>{s.win_rate != null ? `${s.win_rate}%` : "累積中"}</td>
                      <td className={pctClass(s.avg_return_5d)}>{renderPct(s.avg_return_5d)}</td>
                      <td className={pctClass(s.avg_return_10d)}>{renderPct(s.avg_return_10d)}</td>
                      <td className={pctClass(s.avg_return_20d)}>{renderPct(s.avg_return_20d)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <h3 className="paper-section-title">Claude 自動交易帳戶實際績效</h3>
          <div className="ranking-table-wrap">
            <table className="result-table">
              <thead>
                <tr>
                  <th>帳戶</th><th>已平倉次數</th><th>勝率</th>
                  <th>平均獲利</th><th>平均虧損</th><th>損益比</th><th>累計已實現損益</th>
                </tr>
              </thead>
              <tbody>
                {perfRows.map(({ label, perf }) => (
                  <tr key={label}>
                    <td className="col-ticker">{label}</td>
                    {!perf || perf.total_trades === 0 ? (
                      <td colSpan={6} className="no-data">尚無已平倉交易</td>
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
