import type { Item } from "../types";
import ItemCard from "./ItemCard";

interface Props {
  items: Item[];
}

export default function ClosetGrid({ items }: Props) {
  if (items.length === 0) {
    return (
      <div style={{ textAlign: "center", padding: "80px 0", color: "#9ca3af" }}>
        <p style={{ fontSize: "1.1rem", margin: "0 0 8px" }}>Your closet is empty</p>
        <p style={{ fontSize: "0.9rem", margin: 0 }}>Click "Initialize closet" to scan your purchase emails</p>
      </div>
    );
  }

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
        gap: "16px",
        paddingBottom: "32px",
      }}
    >
      {items.map((item) => (
        <ItemCard key={item.id} item={item} />
      ))}
    </div>
  );
}
