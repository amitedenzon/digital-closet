import { useState } from "react";
import type { CSSProperties } from "react";

interface Props {
  onInit: (stopYear: number) => void;
  onSync: () => void;
  syncing: boolean;
}

export default function Header({ onInit, onSync, syncing }: Props) {
  const [showYearPrompt, setShowYearPrompt] = useState(false);
  const [stopYear, setStopYear] = useState("2023");

  const handleInitClick = () => {
    if (syncing) return;
    setShowYearPrompt(true);
  };

  const handleInitConfirm = () => {
    const year = parseInt(stopYear, 10);
    if (!isNaN(year) && year >= 2000 && year <= new Date().getFullYear()) {
      setShowYearPrompt(false);
      onInit(year);
    }
  };

  return (
    <header style={{ padding: "16px 0", display: "flex", alignItems: "center", gap: "12px", borderBottom: "1px solid #ddd", marginBottom: "16px" }}>
      <h1 style={{ margin: 0, fontSize: "1.5rem", flex: 1 }}>Digital Closet</h1>
      {showYearPrompt ? (
        <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
          <label style={{ fontSize: "0.9rem" }}>
            Scan back to year:
            <input
              type="number"
              value={stopYear}
              min={2000}
              max={new Date().getFullYear()}
              onChange={(e) => setStopYear(e.target.value)}
              style={{ marginLeft: "8px", width: "70px", padding: "4px" }}
            />
          </label>
          <button onClick={handleInitConfirm} style={btnStyle}>Start</button>
          <button onClick={() => setShowYearPrompt(false)} style={{ ...btnStyle, background: "#999" }}>Cancel</button>
        </div>
      ) : (
        <>
          <button onClick={handleInitClick} disabled={syncing} style={btnStyle}>
            Initialize closet
          </button>
          <button onClick={onSync} disabled={syncing} style={btnStyle}>
            Sync since last check
          </button>
        </>
      )}
    </header>
  );
}

const btnStyle: CSSProperties = {
  padding: "8px 16px",
  background: "#1a1a1a",
  color: "#fff",
  border: "none",
  borderRadius: "4px",
  cursor: "pointer",
  fontSize: "0.9rem",
};
