import { createContext, useContext, useMemo, useState } from "react";
import {
  PLAN_LABELS,
  PLAN_RANK,
  featureById,
  planAtLeast,
  readStoredPlan,
  storePlan,
  type FeatureId,
  type PlanId,
} from "../services/plans";

/**
 * Which plan this browser is on.
 *
 * There is no customer account or payment integration yet, so this is a DEMO entitlement: the
 * current plan lives in localStorage and the plans page offers an explicitly-labelled "演示解锁"
 * switch. It exists so the gated product can be demonstrated end to end; it is not a permission
 * boundary and must never be described as one. When customers exist, this becomes the plan field
 * of their account, checked by the server on the same feature ids.
 */
interface EntitlementsState {
  plan: PlanId;
  setPlan: (plan: PlanId) => void;
  has: (feature: FeatureId) => boolean;
  canUse: (minimum: PlanId) => boolean;
  label: string;
  /** True while this is the local demo switch (always, until real billing exists). */
  demo: boolean;
}

const EntitlementsContext = createContext<EntitlementsState | null>(null);

export function EntitlementsProvider({
  children,
  initialPlan,
}: {
  children: React.ReactNode;
  /** Tests seed a plan instead of touching localStorage. */
  initialPlan?: PlanId;
}) {
  const [plan, setPlanState] = useState<PlanId>(() => initialPlan ?? readStoredPlan());
  const value = useMemo<EntitlementsState>(
    () => ({
      plan,
      setPlan: (next: PlanId) => {
        storePlan(next);
        setPlanState(next);
      },
      has: (feature: FeatureId) => planAtLeast(plan, featureById(feature).minimum),
      canUse: (minimum: PlanId) => planAtLeast(plan, minimum),
      label: PLAN_LABELS[plan],
      demo: true,
    }),
    [plan],
  );
  return (
    <EntitlementsContext.Provider value={value}>{children}</EntitlementsContext.Provider>
  );
}

export function useEntitlements(): EntitlementsState {
  const value = useContext(EntitlementsContext);
  if (!value) throw new Error("Missing EntitlementsProvider");
  return value;
}

export { PLAN_RANK };
