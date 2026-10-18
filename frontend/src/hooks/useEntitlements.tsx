import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import {
  ANONYMOUS_ACCOUNT,
  loadAccount,
  loginAccount,
  logoutAccount,
  registerAccount,
  type AccountState,
  type RegisterPayload,
} from "../services/account";
import { PLAN_LABELS, featureById, planAtLeast, type FeatureId, type PlanId } from "../services/plans";

/**
 * The customer account and the plan derived from it.
 *
 * The effective plan comes from the server (backend/accounts.py derives it from the trial and
 * subscription dates on every request), so an expired trial locks the paid workflow without any
 * client cooperation. Anonymous visitors are `free`.
 *
 * The old localStorage "demo unlock" is gone: a plan now requires a real account, and a paid
 * period requires an operator to confirm the offline payment.
 */
interface AccountContextValue {
  state: AccountState;
  loading: boolean;
  /** Set when the initial load failed (network), not for "not logged in". */
  error: string;
  refresh: () => Promise<void>;
  login: (login: string, password: string) => Promise<void>;
  register: (payload: RegisterPayload) => Promise<void>;
  logout: () => Promise<void>;
}

const AccountContext = createContext<AccountContextValue | null>(null);

export function AccountProvider({
  children,
  initialState,
}: {
  children: React.ReactNode;
  /** Tests seed an account instead of calling the API. */
  initialState?: AccountState;
}) {
  const [state, setState] = useState<AccountState>(initialState ?? ANONYMOUS_ACCOUNT);
  const [loading, setLoading] = useState(!initialState);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      setState(await loadAccount());
      setError("");
    } catch (loadError) {
      // The site is usable without an account: a failed account load means anonymous, not broken.
      setState(ANONYMOUS_ACCOUNT);
      setError(loadError instanceof Error ? loadError.message : "账户状态读取失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!initialState) void refresh();
  }, [initialState, refresh]);

  const login = useCallback(async (loginName: string, password: string) => {
    setState(await loginAccount(loginName, password));
    setError("");
  }, []);

  const register = useCallback(async (payload: RegisterPayload) => {
    setState(await registerAccount(payload));
    setError("");
  }, []);

  const logout = useCallback(async () => {
    try {
      setState(await logoutAccount());
    } finally {
      setState(ANONYMOUS_ACCOUNT);
    }
  }, []);

  const value = useMemo<AccountContextValue>(
    () => ({ state, loading, error, refresh, login, register, logout }),
    [state, loading, error, refresh, login, register, logout],
  );
  return <AccountContext.Provider value={value}>{children}</AccountContext.Provider>;
}

export function useAccount(): AccountContextValue {
  const value = useContext(AccountContext);
  if (!value) throw new Error("Missing AccountProvider");
  return value;
}

export interface Entitlements {
  plan: PlanId;
  authenticated: boolean;
  label: string;
  canUse: (minimum: PlanId) => boolean;
  has: (feature: FeatureId) => boolean;
  /** True when the account exists but has no paid period left (expired trial, cancelled). */
  expired: boolean;
}

/** The plan-derived capability view used by the navigation, the gate and the hotel page. */
export function useEntitlements(): Entitlements {
  const { state } = useAccount();
  const plan = state.account?.plan ?? "free";
  return useMemo(
    () => ({
      plan,
      authenticated: state.authenticated,
      label: PLAN_LABELS[plan],
      canUse: (minimum: PlanId) => planAtLeast(plan, minimum),
      has: (feature: FeatureId) => planAtLeast(plan, featureById(feature).minimum),
      expired: state.authenticated && plan === "free",
    }),
    [plan, state.authenticated],
  );
}
