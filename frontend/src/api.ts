import type { Item, JobStatus } from "./types";

export async function startInit(stopYear: number): Promise<{ job_id: string }> {
  const res = await fetch("/sync/init", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ stop_year: stopYear }),
  });
  if (!res.ok) throw new Error(`sync/init failed: ${res.status}`);
  return res.json();
}

export async function startCheckpoint(): Promise<{ job_id: string }> {
  const res = await fetch("/sync/checkpoint", { method: "POST" });
  if (!res.ok) throw new Error(`sync/checkpoint failed: ${res.status}`);
  return res.json();
}

export async function getJobStatus(jobId: string): Promise<JobStatus> {
  const res = await fetch(`/sync/status/${jobId}`);
  if (!res.ok) throw new Error(`sync/status failed: ${res.status}`);
  return res.json();
}

export async function fetchItems(params: {
  vendor?: string;
  brand?: string;
  status?: string;
  q?: string;
}): Promise<Item[]> {
  const qs = new URLSearchParams();
  if (params.vendor) qs.set("vendor", params.vendor);
  if (params.brand) qs.set("brand", params.brand);
  if (params.status) qs.set("status", params.status);
  if (params.q) qs.set("q", params.q);
  const query = qs.toString();
  const res = await fetch(query ? `/items?${query}` : "/items");
  if (!res.ok) throw new Error(`/items failed: ${res.status}`);
  return res.json();
}

export function imageUrl(itemId: string): string {
  return `/images/${itemId}`;
}
