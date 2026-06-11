import type { JobStatus } from "../types";

interface Props {
  status: JobStatus;
}

export default function ProgressBar({ status }: Props) {
  return (
    <div style={{ background: "#fff", border: "1px solid #ddd", borderRadius: "6px", padding: "12px 16px", marginBottom: "16px" }}>
      <div style={{ display: "flex", gap: "24px", fontSize: "0.85rem", color: "#555", marginBottom: "8px" }}>
        <span>Scanned: <strong>{status.scanned}</strong></span>
        <span>Kept: <strong style={{ color: "#16a34a" }}>{status.kept}</strong></span>
        <span>Skipped: <strong>{status.skipped}</strong></span>
        {status.errors > 0 && <span>Errors: <strong style={{ color: "#dc2626" }}>{status.errors}</strong></span>}
        <span style={{ marginLeft: "auto" }}>{status.done ? (status.state === "error" ? "Failed" : "Done") : "Running..."}</span>
      </div>
      {!status.done && (
        <div style={{ height: "4px", background: "#e5e7eb", borderRadius: "2px", overflow: "hidden" }}>
          <div
            style={{
              height: "100%",
              background: "#1a1a1a",
              width: status.scanned > 0 ? `${Math.min(100, (status.kept + status.skipped) / status.scanned * 100)}%` : "10%",
              transition: "width 0.3s ease",
            }}
          />
        </div>
      )}
    </div>
  );
}
