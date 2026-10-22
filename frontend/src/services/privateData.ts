/**
 * A hotel's own private ledger.
 *
 * The tenant is resolved by the backend from the session cookie; this module never sends a
 * hotel id, because a parameter that selects the hotel would let any signed-in customer read
 * another hotel's numbers by editing it.
 *
 * Imports are two-step on purpose. The first call stores nothing and returns what would be
 * written plus every row the file could not be read as; the second re-sends the same bytes and
 * mapping, and the backend parses and validates them again rather than trusting anything the
 * browser echoes back.
 */

export type PrivateMetric =
  | "occupancy_pct"
  | "adr"
  | "room_nights"
  | "channel_share"
  | "room_type_share";

export const PRIVATE_METRIC_LABELS: Record<PrivateMetric, string> = {
  occupancy_pct: "入住率",
  adr: "平均房价",
  room_nights: "间夜",
  channel_share: "渠道占比",
  room_type_share: "房型结构",
};

export const PRIVATE_METRIC_UNITS: Partial<Record<PrivateMetric, string>> = {
  occupancy_pct: "%",
  channel_share: "%",
  room_type_share: "%",
};

export interface PrivateRow {
  id: string;
  metric: PrivateMetric;
  period_start: string;
  period_end: string | null;
  channel: string | null;
  room_type: string | null;
  value: number;
  uploaded_by: string;
  uploaded_at: string;
  source_file: string | null;
}

export interface PrivateSummary {
  tenant: string;
  metrics: PrivateMetric[];
  rows: PrivateRow[];
  count: number;
}

export interface ImportIssue {
  row: number;
  reason: string;
}

export interface ImportPreview {
  tenant: string;
  dryRun: boolean;
  headers: string[];
  mapping: Record<string, string>;
  metrics: PrivateMetric[];
  rowsRead: number;
  acceptedCount: number;
  issues: ImportIssue[];
  sample: {
    metric: PrivateMetric;
    period_start: string;
    period_end: string | null;
    value: number;
    channel: string | null;
    room_type: string | null;
  }[];
  written?: number;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, cache: "no-store" });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail =
      body && typeof body.detail === "string"
        ? body.detail
        : `请求失败 (${response.status})`;
    const error = new Error(detail) as Error & { status?: number };
    error.status = response.status;
    throw error;
  }
  return body as T;
}

export function loadPrivateMetrics(): Promise<PrivateSummary> {
  return call<PrivateSummary>("/api/private/metrics");
}

export interface TenantMember {
  login: string;
  role: "owner" | "member";
  added_at: string;
}

export interface MemberList {
  tenant: string;
  login: string | null;
  canManage: boolean;
  members: TenantMember[];
}

export function loadMembers(): Promise<MemberList> {
  return call<MemberList>("/api/tenant/members");
}

/** Add an already-registered account to this hotel. Owners only; the backend enforces it. */
export function addMember(login: string): Promise<{ tenant_id: string; login: string }> {
  return call("/api/tenant/members", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ login }),
  });
}

export function removeMember(login: string): Promise<{ removed: string }> {
  return call(`/api/tenant/members/${encodeURIComponent(login)}`, { method: "DELETE" });
}

/** @param mapping columns the customer confirmed, as `{ metric: headerName }` */
export function importSpreadsheet(
  file: File,
  options: { apply: boolean; mapping?: Record<string, string> },
): Promise<ImportPreview> {
  const params = new URLSearchParams({ filename: file.name });
  params.set("apply", options.apply ? "1" : "0");
  if (options.mapping) params.set("mapping", JSON.stringify(options.mapping));
  return file.arrayBuffer().then((bytes) =>
    call<ImportPreview>(`/api/private/import?${params.toString()}`, {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: bytes,
    }),
  );
}
