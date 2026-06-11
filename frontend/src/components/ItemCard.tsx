import { useState } from "react";
import type { Item } from "../types";
import { imageUrl } from "../api";

interface Props {
  item: Item;
}

export default function ItemCard({ item }: Props) {
  const [imgError, setImgError] = useState(false);
  const dimmed = item.status !== "active";

  return (
    <article
      style={{
        background: "#fff",
        borderRadius: "8px",
        overflow: "hidden",
        border: "1px solid #e5e7eb",
        opacity: dimmed ? 0.55 : 1,
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div style={{ aspectRatio: "1", background: "#f9fafb", position: "relative" }}>
        {!imgError ? (
          <img
            src={imageUrl(item.id)}
            alt={item.item_name}
            onError={() => setImgError(true)}
            style={{ width: "100%", height: "100%", objectFit: "cover" }}
          />
        ) : (
          <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: "#aaa", fontSize: "0.8rem" }}>
            No image
          </div>
        )}
        {dimmed && (
          <span style={{
            position: "absolute",
            top: "8px",
            right: "8px",
            background: item.status === "returned" ? "#dc2626" : "#6b7280",
            color: "#fff",
            fontSize: "0.7rem",
            fontWeight: 600,
            padding: "2px 6px",
            borderRadius: "4px",
            textTransform: "uppercase",
          }}>
            {item.status}
          </span>
        )}
      </div>
      <div style={{ padding: "12px", flex: 1, display: "flex", flexDirection: "column", gap: "4px" }}>
        <p style={{ margin: 0, fontWeight: 600, fontSize: "0.95rem", lineHeight: 1.3 }}>{item.item_name}</p>
        {item.brand && <p style={{ margin: 0, fontSize: "0.8rem", color: "#6b7280" }}>{item.brand}</p>}
        <div style={{ display: "flex", gap: "8px", fontSize: "0.8rem", color: "#9ca3af", flexWrap: "wrap" }}>
          {item.size && <span>Size: {item.size}</span>}
          {item.color && <span>{item.color}</span>}
        </div>
        <div style={{ marginTop: "auto", display: "flex", justifyContent: "space-between", alignItems: "center", paddingTop: "8px" }}>
          {item.price != null ? (
            <span style={{ fontWeight: 600 }}>${item.price.toFixed(2)}</span>
          ) : (
            <span />
          )}
          <span style={{ fontSize: "0.75rem", color: "#9ca3af" }}>
            {item.vendor_domain} · {new Date(item.purchase_date).toLocaleDateString()}
          </span>
        </div>
      </div>
    </article>
  );
}
