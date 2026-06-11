export interface Item {
  id: string;
  order_id: string;
  item_name: string;
  brand: string | null;
  size: string | null;
  color: string | null;
  quantity: number;
  price: number | null;
  status: "active" | "returned" | "cancelled";
  vendor_name: string;
  vendor_domain: string;
  purchase_date: string;
  created_at: string;
}

export interface JobStatus {
  job_id: string;
  state: "running" | "done" | "error";
  scanned: number;
  kept: number;
  skipped: number;
  errors: number;
  done: boolean;
}

export interface Filters {
  vendor: string;
  brand: string;
  status: string;
  q: string;
}
