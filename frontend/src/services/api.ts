import { normalizeDataset } from "./adapter";
import type { Dataset, Status } from "../types";

export interface PipelineStatus {
  sourceCount: number;
  mockSourceCount: number;
  eventCount: number;
  demoEventCount: number;
  verificationCounts: Record<Status, number>;
  lastUpdated: string | null;
  revision: number;
  /** 后端口径版本（GPT Round 6 要求由后端提供，前端不维护副本）。 */
  caliberVersion?: string | null;
  sources: {
    id: string;
    name: string;
    kind: string;
    mock: number;
    source_url: string | null;
  }[];
}
export interface ApiSnapshot {
  dataset: Dataset;
  status: PipelineStatus;
}
export type ReviewDecision = "Verified" | "Rejected" | "Corrected";

export interface VenueDuplicate {
  alias_id: string;
  alias_name: string;
  alias_events: number;
  canonical_id: string;
  canonical_name: string;
  canonical_events: number;
  canonical_has_coordinates: boolean;
  signal: "exact" | "containment" | "proximity";
  distance_km: number | null;
  alias_looks_like_address: boolean;
  notes: string[];
}

export interface CoordinateTarget {
  id: string;
  name: string;
  address: string | null;
  events: number;
  has_coordinates: boolean;
  coordinates: {
    lng: number;
    lat: number;
    system: string;
    status: string;
    sourceUrl: string | null;
  } | null;
}

async function jsonBody(response: Response, what: string) {
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${what}失败 (${response.status}): ${detail.slice(0, 200)}`);
  }
  return response.json();
}

export async function loadVenueDuplicates(): Promise<VenueDuplicate[]> {
  return jsonBody(await fetch("/api/venues/duplicates", { cache: "no-store" }), "读取重复场馆");
}

export async function loadCoordinateTargets(): Promise<CoordinateTarget[]> {
  return jsonBody(
    await fetch("/api/venues/coordinates/needed", { cache: "no-store" }),
    "读取待补坐标场馆",
  );
}

export async function mergeVenues(input: {
  aliasId: string;
  canonicalId: string;
  reviewer: string;
  reason: string;
  evidenceUrl?: string;
}): Promise<{ events_moved: number }> {
  return jsonBody(
    await fetch("/api/venues/merge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        alias_id: input.aliasId,
        canonical_id: input.canonicalId,
        reviewer: input.reviewer,
        reason: input.reason,
        evidence_url: input.evidenceUrl ?? null,
      }),
    }),
    "合并场馆",
  );
}

export async function setVenueCoordinates(input: {
  venueId: string;
  /** The pair exactly as AMap's 坐标拾取 copies it: "120.704315,31.322250". */
  coordinates: string;
  /** Optional; the API resolves the AMap place from the coordinate when omitted. */
  sourceUrl?: string;
  reviewer: string;
  note?: string;
}): Promise<{ coordinates: unknown }> {
  return jsonBody(
    await fetch("/api/venues/coordinates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        venue_id: input.venueId,
        coordinates: input.coordinates,
        source_url: input.sourceUrl ?? null,
        reviewer: input.reviewer,
        note: input.note ?? null,
      }),
    }),
    "保存坐标",
  );
}

export interface EventCheckResult {
  event_id: string;
  approved: string[];
  confirmed_absent: string[];
  already_verified: string[];
  conflicts_left_for_manual_review: string[];
  not_applicable: string[];
  settled: number;
  needs_attention: number;
  venue_reference_status: string | null;
}

/** Settle every factual field of one event, and report what remains. */
export async function checkWholeEvent(input: {
  eventId: string;
  reviewer: string;
}): Promise<EventCheckResult> {
  return jsonBody(
    await fetch("/api/review/event", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ event_id: input.eventId, reviewer: input.reviewer }),
    }),
    "全部核查完毕",
  );
}

export interface ManualEventInput {
  name: string;
  category: string;
  startDate: string;
  endDate: string | null;
  venueName: string | null;
  district: string | null;
  note: string | null;
}

/** Enter one event by hand for material no crawlable source publishes. */
export async function submitManualEvent(input: ManualEventInput): Promise<{ id: string }> {
  return jsonBody(
    await fetch("/api/admin/events", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
    "录入活动",
  );
}


export interface CrawlSourceHealth {
  source_id: string;
  source_name: string | null;
  runs: number;
  failures: number;
  last_run: string | null;
  last_status: string | null;
  last_events_found: number | null;
  last_failure_reason: string | null;
  consecutive_failures: number;
  alert_raised_at: string | null;
}

export interface CrawlAlert {
  source_id: string;
  source_name: string | null;
  consecutive_failures: number;
  reason: string | null;
  raised_at: string;
}

/** Per-source crawl health, including any source that has stopped working. */
export async function loadCrawlHealth(): Promise<{
  sources: CrawlSourceHealth[];
  alerts: CrawlAlert[];
}> {
  return jsonBody(
    await fetch("/api/crawl/health", { cache: "no-store" }),
    "读取采集状态",
  );
}

export interface ClientErrorReport {
  message: string;
  source?: string;
  stack?: string;
  page?: string;
  userAgent?: string;
  viewport?: string;
  extra?: Record<string, unknown>;
}

/**
 * Send a browser-side error to the server.
 *
 * Used by the ErrorBoundary and by the global window.onerror handler, so a crash on a phone is
 * recorded somewhere it can actually be read. Never throws: the caller has already failed once.
 */
export async function reportClientError(
  report: ClientErrorReport,
): Promise<void> {
  await fetch("/api/client-error", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(report),
    // Survives the page being navigated away from or reloaded mid-report.
    keepalive: true,
  });
}

export interface StoredClientError {
  id: number;
  occurred_at: string;
  message: string | null;
  source: string | null;
  stack: string | null;
  page: string | null;
  user_agent: string | null;
  viewport: string | null;
  /** The failing script's URL and position, when the browser reported them. */
  extra: Record<string, unknown> | null;
}

/** Recent browser-side errors, newest first. Internal: the API requires a reviewer role. */
export async function loadClientErrors(limit = 50): Promise<StoredClientError[]> {
  return jsonBody(
    await fetch(`/api/client-errors?limit=${limit}`, { cache: "no-store" }),
    "读取前端错误",
  );
}

/**
 * Who is behind this browser.
 *
 * The backend maps the nginx basic-auth login to a role (admin / reviewer / viewer). The public
 * pages need nothing but the dataset; the review console needs this to decide whether to render
 * at all, and still relies on the SERVER to enforce the rule — hiding a button is not a
 * permission. Failing to load it is treated as anonymous: a customer account is a normal case.
 */
export interface Identity {
  authenticated: boolean;
  login: string | null;
  role: "admin" | "reviewer" | "viewer" | null;
  name?: string | null;
}

export const ANONYMOUS: Identity = {
  authenticated: false,
  login: null,
  role: null,
};

export async function loadIdentity(): Promise<Identity> {
  const body = await jsonBody(
    await fetch("/api/auth/me", { cache: "no-store" }),
    "读取当前身份",
  );
  const role =
    body?.role === "admin" || body?.role === "viewer" || body?.role === "reviewer"
      ? body.role
      : null;
  return {
    authenticated: Boolean(body?.authenticated),
    login: typeof body?.login === "string" ? body.login : null,
    role,
    name: typeof body?.name === "string" ? body.name : null,
  };
}

/** True for roles allowed to use the review console. The server checks this again. */
export function canReview(identity: Identity | null): boolean {
  return identity?.role === "admin" || identity?.role === "reviewer";
}

export interface ReviewRecord {
  event_id: string;
  field: string;
  decision: ReviewDecision;
  reviewed_value: string | null;
  corrected_value: string | null;
  reviewer: string;
  note: string | null;
  decided_at: string;
}

/** The decision log. Internal: the API requires a reviewer role. */
export async function loadReviewQueue(): Promise<ReviewRecord[]> {
  return jsonBody(
    await fetch("/api/review", { cache: "no-store" }),
    "读取审核记录",
  );
}

export async function submitReview(input: {
  eventId: string;
  field: string;
  decision: ReviewDecision;
  value?: unknown;
  correctedValue?: unknown;
  reviewer: string;
  note?: string;
}): Promise<ReviewRecord> {
  const response = await fetch("/api/review", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      event_id: input.eventId,
      field: input.field,
      decision: input.decision,
      value: input.value ?? null,
      corrected_value: input.correctedValue ?? null,
      reviewer: input.reviewer,
      note: input.note ?? null,
    }),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`审核提交失败 (${response.status}): ${detail.slice(0, 200)}`);
  }
  return (await response.json()) as ReviewRecord;
}

export async function clearReview(
  eventId: string,
  field: string,
): Promise<void> {
  const response = await fetch(
    `/api/review/${encodeURIComponent(eventId)}/${encodeURIComponent(field)}`,
    { method: "DELETE" },
  );
  if (!response.ok) throw new Error(`撤回失败 (${response.status})`);
}

/**
 * How long a first load may take.
 *
 * The dataset is ~5 MB of JSON (~1.2 MB gzipped) and 87% of it is evidence rows. On a phone
 * that was measured at 11 seconds, which the old 10-second abort turned into a failed page for
 * a request that would have succeeded. The budget is deliberately generous: a slow first load
 * is a better outcome than no page. Repeat loads are cheap — the endpoint sends an ETag and the
 * browser revalidates to a 304 with no body (see `cache: "no-cache"` below).
 */
export const DATASET_TIMEOUT_MS = 45_000;

export async function loadApiDataset(
  signal?: AbortSignal,
): Promise<ApiSnapshot> {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  signal?.addEventListener("abort", cancel, { once: true });
  if (signal?.aborted) controller.abort();
  const timer = setTimeout(() => controller.abort(), DATASET_TIMEOUT_MS);
  try {
    const response = await fetch("/api/dataset", {
      signal: controller.signal,
      // Revalidate with the ETag instead of always re-downloading: "no-store" made every page
      // load fetch the whole snapshot again.
      cache: "no-cache",
    });
    if (!response.ok) throw new Error(`API 请求失败 (${response.status})`);
    const body = await response.json();
    if (
      !body ||
      !["events", "venues", "hotels", "districts", "places", "evidence"].every(
        (key) => Array.isArray(body[key]),
      ) ||
      !body.status ||
      !Array.isArray(body.status.sources) ||
      body.status.eventCount !== body.events.length ||
      body.status.sourceCount !== body.status.sources.length ||
      (body.updatedAt !== null &&
        (typeof body.updatedAt !== "string" ||
          Number.isNaN(Date.parse(body.updatedAt))))
    ) {
      throw new Error("API 数据结构不完整，未替换当前数据");
    }
    const dataset = normalizeDataset(body);
    // An empty database must not acquire a fabricated "last updated" timestamp.
    dataset.updatedAt = body.updatedAt ?? "";
    return { dataset, status: body.status };
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", cancel);
  }
}

// ---- 商圈（business area）聚合：数据来自后端 /market/*，前端不做距离计算 ----
export interface MarketCoverage {
  radiusMeters: number;
  areaCount: number;
  areaWithCenter: number;
  areaVerified: number;
  areaLowQuality: number;
  venuesTotal: number;
  venuesWithVerifiedCoords: number;
  eventsTotal: number;
  eventsNearby: number;
  eventsAmbiguous: number;
  eventsUnmatched: number;
  note: string;
}

export interface MarketAreaRow {
  id: string;
  name: string;
  parentName: string | null;
  quality: string;
  centerSource: string | null;
  radiusMeters: number;
  nearbyEvents: number;
  ambiguousEvents: number;
  parentDistrictEvents: number;
}

export interface MarketAreaProfile {
  area: {
    id: string;
    name: string;
    parentName: string | null;
    quality: string;
    radiusMeters: number;
    center: {
      lng: number;
      lat: number;
      system: string | null;
      source: string | null;
      matchedName: string | null;
      adname: string | null;
      matchLevel: string | null;
      matchedAt: string | null;
    };
  };
  window: { start: string | null; end: string | null };
  nearbyEvents: {
    identity: string;
    name: string;
    category: string;
    startDate: string;
    endDate: string | null;
    distanceMeters: number;
  }[];
  ambiguousEvents: {
    identity: string;
    name: string;
    category: string;
    startDate: string;
    endDate: string | null;
    distanceMeters: number;
  }[];
  coverage: {
    method: string;
    matched: number;
    matchedAll: number;
    ambiguous: number;
    ambiguousAll: number;
    parentDistrictEvents: number;
    unmatchedInParent: number;
    venuesWithVerifiedCoords: number;
    venuesTotal: number;
  };
  categories: [string, number][];
  months: [string, number][];
  hotels: { name: string; distanceMeters: number; starLabel: string | null }[];
  caveat: string;
}

function marketQuery(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  });
  const text = search.toString();
  return text ? "?" + text : "";
}

export async function loadMarketCoverage(radius?: number): Promise<MarketCoverage> {
  const response = await fetch("/api/market/coverage" + marketQuery({ radius }));
  if (!response.ok) throw new Error("商圈覆盖数据加载失败");
  return response.json();
}

export async function loadMarketAreas(radius?: number): Promise<MarketAreaRow[]> {
  const response = await fetch("/api/market/areas" + marketQuery({ radius }));
  if (!response.ok) throw new Error("商圈列表加载失败");
  const payload = await response.json();
  return (payload.areas ?? []) as MarketAreaRow[];
}

export async function loadMarketAreaProfile(
  id: string,
  params: { radius?: number; start?: string; end?: string } = {},
): Promise<MarketAreaProfile> {
  const response = await fetch(
    "/api/market/area/" + encodeURIComponent(id) + marketQuery(params),
  );
  if (!response.ok) throw new Error("商圈画像加载失败");
  return response.json();
}
