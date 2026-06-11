import { useState, useEffect, useCallback, useRef } from "react";
import type { Item, JobStatus, Filters } from "./types";
import { startInit, startCheckpoint, getJobStatus, fetchItems } from "./api";
import Header from "./components/Header";
import ProgressBar from "./components/ProgressBar";
import FiltersBar from "./components/Filters";
import ClosetGrid from "./components/ClosetGrid";

export default function App() {
  const [items, setItems] = useState<Item[]>([]);
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null);
  const [filters, setFilters] = useState<Filters>({ vendor: "", brand: "", status: "", q: "" });
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadItems = useCallback(async () => {
    try {
      const data = await fetchItems({
        vendor: filters.vendor || undefined,
        brand: filters.brand || undefined,
        status: filters.status || undefined,
        q: filters.q || undefined,
      });
      setItems(data);
    } catch (e) {
      setError(String(e));
    }
  }, [filters]);

  useEffect(() => {
    loadItems();
  }, [loadItems]);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startPolling = useCallback(
    (jobId: string) => {
      stopPolling();
      pollRef.current = setInterval(async () => {
        try {
          const status = await getJobStatus(jobId);
          setJobStatus(status);
          if (status.done) {
            stopPolling();
            await loadItems();
          }
        } catch {
          stopPolling();
        }
      }, 1000);
    },
    [stopPolling, loadItems]
  );

  const handleInit = useCallback(async (stopYear: number) => {
    setError(null);
    try {
      const { job_id } = await startInit(stopYear);
      const initial = await getJobStatus(job_id);
      setJobStatus(initial);
      startPolling(job_id);
    } catch (e) {
      setError(String(e));
    }
  }, [startPolling]);

  const handleSync = useCallback(async () => {
    setError(null);
    try {
      const { job_id } = await startCheckpoint();
      const initial = await getJobStatus(job_id);
      setJobStatus(initial);
      startPolling(job_id);
    } catch (e) {
      setError(String(e));
    }
  }, [startPolling]);

  const isSyncing = jobStatus !== null && !jobStatus.done;

  return (
    <>
      <Header onInit={handleInit} onSync={handleSync} syncing={isSyncing} />
      {jobStatus && <ProgressBar status={jobStatus} />}
      {error && (
        <p style={{ color: "red", padding: "8px 0" }}>{error}</p>
      )}
      <FiltersBar filters={filters} onChange={setFilters} />
      <ClosetGrid items={items} />
    </>
  );
}
