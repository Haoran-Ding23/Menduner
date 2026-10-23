import {
  createContext,
  useCallback,
  useEffect,
  useRef,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import type { Dataset, Filters } from "../types";
import { createRepository, sampleDataset } from "../services/repository";
import { loadApiDataset, type PipelineStatus } from "../services/api";
import { normalizeDataset } from "../services/adapter";
import { distinctByCanonical } from "../utils/dedupe";
const Context = createContext<ReturnType<typeof useStateValue> | null>(null);
function useStateValue(initialDataset?: Dataset) {
  const [dataset, setDataset] = useState<Dataset>(
    initialDataset ?? {
      events: [],
      venues: [],
      hotels: [],
      districts: [],
      places: [],
      evidence: [],
      updatedAt: "",
    },
  );
  const [dataMode, setDataMode] = useState<
    "loading" | "api" | "error" | "stale" | "demo" | "import"
  >(initialDataset ? "demo" : "loading");
  const [pipelineStatus, setPipelineStatus] = useState<PipelineStatus | null>(
    null,
  );
  const [dataError, setDataError] = useState("");
  const request = useRef<AbortController | null>(null);
  const hasApiData = useRef(false);
  const cancelRequest = () => {
    request.current?.abort();
    request.current = null;
  };
  const reloadData = useCallback(async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    if (!hasApiData.current) {
      setDataset({
        events: [],
        venues: [],
        hotels: [],
        districts: [],
        places: [],
        evidence: [],
        updatedAt: "",
      });
      setPipelineStatus(null);
    }
    setDataMode("loading");
    setDataError("");
    try {
      const result = await loadApiDataset(controller.signal);
      if (controller.signal.aborted) return;
      setDataset(result.dataset);
      setPipelineStatus(result.status);
      hasApiData.current = true;
      setDataMode("api");
    } catch (error) {
      if (controller.signal.aborted) return;
      setDataMode(hasApiData.current ? "stale" : "error");
      setDataError(
        error instanceof Error && error.name !== "AbortError"
          ? error.message
          : "API 连接超时或不可用：数据集约 1.2 MB（压缩后），首次加载在慢网络下可能需要十几秒，请重试",
      );
    }
  }, []);
  useEffect(() => {
    if (!initialDataset) void reloadData();
    return () => request.current?.abort();
  }, [initialDataset, reloadData]);
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const year = Number(params.get("year") ?? 2026),
    month = Number(params.get("month") ?? 10);
  const filters: Filters = {
    year: Number.isInteger(year) && year >= 1900 && year <= 2100 ? year : 2026,
    month: Number.isInteger(month) && month >= 1 && month <= 12 ? month : 10,
    district: params.get("district") ?? "",
    category: params.get("category") ?? "",
    // 演示数据默认关闭：评审要求真实数据优先，DEMO 由用户显式打开（?demo=1）。
    // 原来写成 !== "0"，等于默认开启，任何截图里的数字都会混入演示行。
    includeDemo: params.get("demo") === "1",
    includePast: params.get("past") === "1",
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
  // Events that finished a while ago are history, not a demand signal, and letting them sit in
  // every list and total made a live product read like an archive. They are hidden from the
  // working view but never deleted — the evidence behind them stays queryable, and a reviewer
  // can bring them back with ?past=1.
  const GRACE_DAYS = 30;
  const includePast = params.get("past") === "1";
  const visibleEvents = useMemo(() => {
    if (includePast) return dataset.events;
    const cutoff = new Date(Date.now() - GRACE_DAYS * 86400000)
      .toISOString()
      .slice(0, 10);
    return dataset.events.filter((event) => {
      // Demo/synthetic rows are a fixed fixture, not live demand, so hiding them would only
      // make the demo dataset look broken.
      if (event.demo || dataset.events.every((e) => e.demo)) return true;
      const ends = event.endDate ?? event.startDate;
      return !ends || ends >= cutoff;
    });
  }, [dataset.events, includePast]);
  const archivedCount = dataset.events.length - visibleEvents.length;

  const visibleDataset = useMemo(
    () => (visibleEvents === dataset.events ? dataset : { ...dataset, events: visibleEvents }),
    [dataset, visibleEvents],
  );
  const visibleRepository = useMemo(
    () => (visibleEvents === dataset.events ? repository : createRepository(visibleDataset)),
    [dataset.events, repository, visibleDataset, visibleEvents],
  );
  /**
   * 统一身份层（审核 F04）：同一活动在不同来源下的多条记录只保留一条代表。
   *
   * 放在这里而不是各页面各写一遍，是因为「统计、推荐、图谱、周报用同一套身份」是审核的明确
   * 要求；分散实现会让某个页面漏掉去重，而漏掉的那一页正是用户会看到两个同名活动的地方。
   * 原始记录仍保留在 dataset.events 里，证据页需要逐条记录时照旧可用。
   */
  const identifiedEvents = useMemo(() => distinctByCanonical(visibleEvents), [visibleEvents]);
  const identifiedDataset = useMemo(
    () =>
      identifiedEvents.length === visibleEvents.length
        ? visibleDataset
        : { ...visibleDataset, events: identifiedEvents },
    [identifiedEvents, visibleDataset, visibleEvents],
  );
  const identifiedRepository = useMemo(
    () =>
      identifiedEvents.length === visibleEvents.length
        ? visibleRepository
        : createRepository(identifiedDataset),
    [identifiedDataset, identifiedEvents, visibleEvents.length, visibleRepository],
  );
  return {
    // 默认数据集走身份层：统计、推荐、图谱、地图与周报看到的是同一批活动。
    dataset: identifiedDataset,
    // 未经去重的原始集合，供证据页逐条核对来源与字段冲突（合并后仍要能看到每条原始记录）。
    rawDataset: visibleDataset,
    // The unfiltered set, so a page can count what the archive holds for one region instead of
    // only knowing the global archived total.
    allEvents: dataset.events,
    archivedCount,
    includePast,
    dataMode,
    pipelineStatus,
    dataError,
    reloadData,
    repository: identifiedRepository,
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
      cancelRequest();
      hasApiData.current = false;
      setPipelineStatus(null);
      setDataMode("import");
      setDataError("");
      setDataset(d);
      update({ event: null, detail: null, district: null, category: null });
    },
    resetData: () => {
      cancelRequest();
      hasApiData.current = false;
      setPipelineStatus(null);
      setDataMode("demo");
      setDataError("");
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
export function PlatformProvider({
  children,
  initialDataset,
}: {
  children: ReactNode;
  initialDataset?: Dataset;
}) {
  const value = useStateValue(initialDataset);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
export function usePlatform() {
  const v = useContext(Context);
  if (!v) throw new Error("Missing PlatformProvider");
  return v;
}
