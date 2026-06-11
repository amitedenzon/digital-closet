import { type ChangeEvent } from "react";
import type { CSSProperties } from "react";
import type { Filters } from "../types";

interface Props {
  filters: Filters;
  onChange: (f: Filters) => void;
}

export default function FiltersBar({ filters, onChange }: Props) {
  const set = (key: keyof Filters) => (e: ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    onChange({ ...filters, [key]: e.target.value });

  return (
    <div style={{ display: "flex", gap: "12px", flexWrap: "wrap", marginBottom: "16px" }}>
      <input
        placeholder="Search items..."
        value={filters.q}
        onChange={set("q")}
        style={inputStyle}
      />
      <input
        placeholder="Vendor domain"
        value={filters.vendor}
        onChange={set("vendor")}
        style={{ ...inputStyle, maxWidth: "160px" }}
      />
      <input
        placeholder="Brand"
        value={filters.brand}
        onChange={set("brand")}
        style={{ ...inputStyle, maxWidth: "140px" }}
      />
      <select value={filters.status} onChange={set("status")} style={{ ...inputStyle, maxWidth: "140px" }}>
        <option value="">All statuses</option>
        <option value="active">Active</option>
        <option value="returned">Returned</option>
        <option value="cancelled">Cancelled</option>
      </select>
    </div>
  );
}

const inputStyle: CSSProperties = {
  padding: "8px 12px",
  border: "1px solid #ddd",
  borderRadius: "4px",
  fontSize: "0.9rem",
  flex: 1,
  minWidth: "120px",
};
