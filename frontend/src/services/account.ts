import type { PlanId } from "./plans";

/**
 * The customer's product account: invite-code trial, session cookie, offline payment orders.
 *
 * This is not the operator identity (that is HTTP Basic via nginx for the review console). The
 * session cookie is set by the backend as HttpOnly, so this module only ever sees the account
 * payload; the browser sends the cookie automatically (same-origin fetch).
 */
export type AccountStatus = "trial" | "active" | "expired" | "suspended";

export interface Account {
  id: string;
  login: string;
  name: string;
  hotel: string | null;
  plan: PlanId;
  status: AccountStatus;
  expiresAt: string | null;
  trialEndsAt: string | null;
  subscriptionEndsAt: string | null;
  createdAt: string;
}

export type OrderStatus = "pending" | "confirmed" | "cancelled";

export interface CustomerOrder {
  id: string;
  plan: PlanId;
  months: number;
  amountCny: number;
  note: string | null;
  status: OrderStatus;
  createdAt: string;
  confirmedAt: string | null;
}

export interface AccountState {
  authenticated: boolean;
  account: Account | null;
  orders: CustomerOrder[];
}

export const ANONYMOUS_ACCOUNT: AccountState = {
  authenticated: false,
  account: null,
  orders: [],
};

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail =
      body && typeof body.detail === "string" ? body.detail : `请求失败 (${response.status})`;
    const error = new Error(detail) as Error & { status?: number };
    error.status = response.status;
    throw error;
  }
  return body as T;
}

export function loadAccount(): Promise<AccountState> {
  return call<AccountState>("/api/account");
}

export function loginAccount(login: string, password: string): Promise<AccountState> {
  return call<AccountState>("/api/account/login", {
    method: "POST",
    body: JSON.stringify({ login, password }),
  });
}

export interface RegisterPayload {
  inviteCode: string;
  login: string;
  password: string;
  name: string;
  hotel?: string;
}

export function registerAccount(payload: RegisterPayload): Promise<AccountState> {
  return call<AccountState>("/api/account/register", {
    method: "POST",
    body: JSON.stringify({
      invite_code: payload.inviteCode,
      login: payload.login,
      password: payload.password,
      name: payload.name,
      hotel: payload.hotel || null,
    }),
  });
}

export function logoutAccount(): Promise<AccountState> {
  return call<AccountState>("/api/account/logout", { method: "POST" });
}

export interface ActivationRequest {
  plan: PlanId;
  months: number;
  note?: string;
}

export function requestActivation(payload: ActivationRequest): Promise<{
  order: CustomerOrder;
  account: Account;
}> {
  return call("/api/account/orders", {
    method: "POST",
    body: JSON.stringify({ plan: payload.plan, months: payload.months, note: payload.note || null }),
  });
}

/** Plan display helpers shared by the plans page and the gate. */
export function statusLabel(state: AccountState): string {
  if (!state.authenticated || !state.account) return "未登录";
  const account = state.account;
  switch (account.status) {
    case "trial":
      return `试用中 · ${account.plan === "enterprise" ? "企业版" : "专业版"}`;
    case "active":
      return `已开通 · ${account.plan === "enterprise" ? "企业版" : "专业版"}`;
    case "expired":
      return "试用已结束";
    case "suspended":
      return "已暂停";
    default:
      return "免费版";
  }
}
