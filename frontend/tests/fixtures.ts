import type { Account, AccountState, CustomerOrder } from "../src/services/account";

/** Account fixtures for the frontend tests: the plan the server would derive for each case. */
const base: Account = {
  id: "cus_test_enterprise",
  login: "test-enterprise",
  name: "测试客户",
  hotel: "苏州洲际酒店",
  plan: "enterprise",
  status: "active",
  expiresAt: "2027-10-18T00:00:00+00:00",
  trialEndsAt: "2026-11-15T00:00:00+00:00",
  subscriptionEndsAt: "2027-10-18T00:00:00+00:00",
  createdAt: "2026-10-18T00:00:00+00:00",
};

export const ENTERPRISE_ACCOUNT: AccountState = {
  authenticated: true,
  account: { ...base },
  orders: [],
};

export const TRIAL_PRO_ACCOUNT: AccountState = {
  authenticated: true,
  account: {
    ...base,
    id: "cus_test_pro",
    login: "test-pro",
    plan: "pro",
    status: "trial",
    subscriptionEndsAt: null,
    trialEndsAt: "2026-11-15T00:00:00+00:00",
  },
  orders: [],
};

export const EXPIRED_ACCOUNT: AccountState = {
  authenticated: true,
  account: {
    ...base,
    id: "cus_test_expired",
    login: "test-expired",
    plan: "free",
    status: "expired",
    subscriptionEndsAt: null,
    trialEndsAt: "2026-09-18T00:00:00+00:00",
  },
  orders: [],
};

export const PENDING_ORDER: CustomerOrder = {
  id: "ord_test_pending",
  plan: "pro",
  months: 3,
  amountCny: 2940,
  note: "对公转账",
  status: "pending",
  createdAt: "2026-10-18T00:00:00+00:00",
  confirmedAt: null,
};

export const ANONYMOUS_ACCOUNT_STATE: AccountState = {
  authenticated: false,
  account: null,
  orders: [],
};
