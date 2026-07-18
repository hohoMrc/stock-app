import { useState, useEffect } from "react";
import { getIndustryStocks } from "../api";

export default function IndustryStocks({ industry, excludeTicker, useParent = false, onSelect, onBack }) {
  const [stocks, setStocks] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const res = await getIndustryStocks(industry, excludeTicker, useParent);
        setStocks(res.data.stocks);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [industry, excludeTicker, useParent]);

  return (
    <div className="page">
      <button className="back-btn" onClick={onBack}>← 返回</button>
      <h2>{industry} 相關個股</h2>

      {loading && <p className="loading-hint">查詢中...</p>}

      {!loading && stocks.length === 0 && (
        <p className="no-data">預設清單中未找到其他同產業個股</p>
      )}

      {!loading && stocks.length > 0 && (
        <table className="result-table">
          <thead>
            <tr>
              <th>代號</th>
              <th>名稱</th>
              <th>成交價</th>
              <th>漲跌幅</th>
              <th>漲跌</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {stocks.map((s) => {
              const up   = s.change > 0;
              const down = s.change < 0;
              const sign = up ? "+" : "";
              const dir  = up ? "up" : down ? "down" : "";
              return (
                <tr key={s.ticker} className={up ? "row-up" : down ? "row-down" : ""}>
                  <td>{s.ticker}</td>
                  <td>{s.name}</td>
                  <td>{s.price ?? "—"}</td>
                  <td className={dir}>{s.change_pct != null ? `${sign}${s.change_pct}%` : "—"}</td>
                  <td className={dir}>{s.change != null ? `${sign}${s.change}` : "—"}</td>
                  <td>
                    <button className="view-btn" onClick={() => onSelect(s.ticker)}>
                      查看
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
