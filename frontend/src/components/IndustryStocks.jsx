import { useState, useEffect } from "react";
import { getIndustryStocks } from "../api";

export default function IndustryStocks({ industry, excludeTicker, onSelect, onBack }) {
  const [stocks, setStocks] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const res = await getIndustryStocks(industry, excludeTicker);
        setStocks(res.data.stocks);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [industry, excludeTicker]);

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
              <th>股價</th>
              <th>本益比</th>
              <th>殖利率</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {stocks.map((s) => (
              <tr key={s.ticker}>
                <td>{s.ticker}</td>
                <td>{s.name}</td>
                <td>{s.price ?? "—"}</td>
                <td>{s.pe_ratio?.toFixed(2) ?? "—"}</td>
                <td>{s.dividend_yield ? `${s.dividend_yield}%` : "—"}</td>
                <td>
                  <button className="view-btn" onClick={() => onSelect(s.ticker)}>
                    查看
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
