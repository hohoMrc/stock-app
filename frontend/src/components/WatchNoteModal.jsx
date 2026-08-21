import { useState, useEffect, useRef } from "react";

export default function WatchNoteModal({ ticker, groups = [], onConfirm, onCancel }) {
  const [note, setNote] = useState("");
  const [groupId, setGroupId] = useState(1);
  const inputRef = useRef(null);
  const effectiveGroups = groups.length ? groups : [{ group_id: 1, name: "分組1" }];

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleSubmit = (e) => {
    e.preventDefault();
    onConfirm(ticker, note.trim(), groupId);
  };

  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal-box watch-note-modal" onClick={(e) => e.stopPropagation()}>
        <h3 className="watch-note-title">加入自選 — {ticker}</h3>
        <form onSubmit={handleSubmit} className="auth-form">
          <input
            ref={inputRef}
            type="text"
            placeholder="備注（選填）：為什麼加入這檔？"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            onKeyDown={(e) => e.key === "Escape" && onCancel()}
          />
          <select value={groupId} onChange={(e) => setGroupId(parseInt(e.target.value, 10))}>
            {effectiveGroups.map((g) => (
              <option key={g.group_id} value={g.group_id}>{g.name}</option>
            ))}
          </select>
          <div className="watch-note-actions">
            <button type="button" className="logout-btn" onClick={onCancel}>取消</button>
            <button type="submit" className="auth-submit">加入自選</button>
          </div>
        </form>
      </div>
    </div>
  );
}
