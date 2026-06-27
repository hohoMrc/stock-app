import { useState, useEffect, useRef } from "react";

export default function WatchNoteModal({ ticker, onConfirm, onCancel }) {
  const [note, setNote] = useState("");
  const inputRef = useRef(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleSubmit = (e) => {
    e.preventDefault();
    onConfirm(ticker, note.trim());
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
          <div className="watch-note-actions">
            <button type="button" className="logout-btn" onClick={onCancel}>取消</button>
            <button type="submit" className="auth-submit">加入自選</button>
          </div>
        </form>
      </div>
    </div>
  );
}
