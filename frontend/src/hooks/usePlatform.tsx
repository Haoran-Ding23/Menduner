import {
  createContext,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import type { Dataset, Filters } from "../types";
import { createRepository, sampleDataset } from "../services/repository";
import { normalizeDataset } from "../services/adapter";
const Context = createContext<ReturnType<typeof useStateValue> | null>(null);
function useStateValue() {
  const [dataset, setDataset] = useState<Dataset>(sampleDataset);
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const year = Number(params.get("year") ?? 2026),
    month = Number(params.get("month") ?? 10);
  const filters: Filters = {
    year: Number.isInteger(year) && year >= 1900 && year <= 2100 ? year : 2026,
    month: Number.isInteger(month) && month >= 1 && month <= 12 ? month : 10,
    district: params.get("district") ?? "",
    category: params.get("category") ?? "",
    includeDemo: params.get("demo") !== "0",
  };
  const update = (values: Record<string, string | number | null>) => {
    const next = new URLSearchParams(params);
    Object.entries(values).forEach(([k, v]) => {
      if (v === null || v === "") next.delete(k);
      else next.set(k, String(v));
    });
    setParams(next);
  };
  const repository = useMemo(() => createRepository(dataset), [dataset]);
  const go = (
    path: string,
    id?: string,
    extras: Record<string, string | number> = {},
  ) => {
    const next = new URLSearchParams(params);
    next.delete("detail");
    if (id) {
      next.set("event", id);
      const event = repository.getEventById(id);
      if (event?.startDate) {
        next.set("year", event.startDate.slice(0, 4));
        next.set("month", String(Number(event.startDate.slice(5, 7))));
      }
      next.delete("district");
      next.delete("category");
    }
    Object.entries(extras).forEach(([key, value]) =>
      next.set(key, String(value)),
    );
    navigate(path + "?" + next.toString());
  };
  return {
    dataset,
    repository,
    filters,
    params,
    update,
    go,
    selected: params.get("event"),
    detail: params.get("detail"),
    openEvent: (id: string) => update({ event: id, detail: id }),
    closeEvent: () => update({ detail: null }),
    importData: (data: unknown) => {
      const d = normalizeDataset(data);
      setDataset(d);
      update({ event: null, detail: null, district: null, category: null });
    },
    resetData: () => {
      setDataset(sampleDataset);
      update({
        year: 2026,
        month: 10,
        event: null,
        detail: null,
        district: null,
        category: null,
        demo: 1,
      });
    },
  };
}
export function PlatformProvider({ children }: { children: ReactNode }) {
  const value = useStateValue();
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
export function usePlatform() {
  const v = useContext(Context);
  if (!v) throw new Error("Missing PlatformProvider");
  return v;
}
