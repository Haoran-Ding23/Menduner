import type { PlanId } from "./plans";

/**
 * Operator endpoints for the customer side: invite codes, customer list, and the offline payment
 * queue. These URLs are HTTP Basic-protected by nginx and again admin-checked by the backend, so
 * the browser's cached operator credentials answer the challenge (like the review console).
 */
export interface AdminInvite {
  code: string;
  plan: PlanId;
  trialDays: number;
  maxUses: number;
  usedCount: number;
  note: string | null;
  createdBy: string;
  createdAt: string;
  expiresAt: string | null;
  status: "open" | "used" | "expired";
}

export interface AdminAccount {
  id: string;
  login: string;
  name: string;
  hotel: string | null;
  plan: PlanId;
  status: "trial" | "active" | "expired" | "suspended" | "free";
  trialEndsAt: string | null;
  subscriptionEndsAt: string | null;
  expiresAt: string | null;
  createdAt: string;
  lastLoginAt: string | null;
  pendingOrders: number;
}

export type AdminOrderStatus = "pending" | "confirmed" | "cancelled";

export interface AdminOrder {
  id: string;
  plan: PlanId;
  months: number;
  amountCny: number;
  note: string | null;
  status: AdminOrderStatus;
  createdAt: string;
  confirmedAt: string | null;
  confirmedBy: string | null;
  accountLogin: string;
  accountName: string;
  accountHotel: string | null;
}

export class AdminAuthError extends Error {
  constructor() {
    super("需要管理员登录");
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (response.status === 401) throw new AdminAuthError();
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail =
      body && typeof body.detail === "string" ? body.detail : `请求失败 (${response.status})`;
    throw new Error(detail);
  }
  return body as T;
}

export async function loadInvites(): Promise<AdminInvite[]> {
  return (await call<{ invites: AdminInvite[] }>("/api/admin/invites")).invites;
}

export async function createInvite(payload: {
  plan: PlanId;
  trialDays: number;
  maxUses: number;
  note?: string;
}): Promise<AdminInvite> {
  const body = await call<{ invite: AdminInvite }>("/api/admin/invites", {
    method: "POST",
    body: JSON.stringify({
      plan: payload.plan,
      trial_days: payload.trialDays,
      max_uses: payload.maxUses,
      expires_in_days: 30,
      note: payload.note || null,
    }),
  });
  return body.invite;
}

export async function loadAccounts(): Promise<AdminAccount[]> {
  return (await call<{ accounts: AdminAccount[] }>("/api/admin/accounts")).accounts;
}

export async function loadOrders(status?: AdminOrderStatus): Promise<AdminOrder[]> {
  const query = status ? `?status=${status}` : "";
  return (await call<{ orders: AdminOrder[] }>(`/api/admin/orders${query}`)).orders;
}

export async function confirmOrder(orderId: string): Promise<AdminOrder> {
  const body = await call<{ order: AdminOrder }>(`/api/admin/orders/${orderId}/confirm`, {
    method: "POST",
  });
  return body.order;
}

export async function cancelOrder(orderId: string): Promise<AdminOrder> {
  const body = await call<{ order: AdminOrder }>(`/api/admin/orders/${orderId}/cancel`, {
    method: "POST",
  });
  return body.order;
}
