import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ANONYMOUS,
  canReview,
  isAdmin,
  loadIdentity,
  type Identity,
} from "../services/api";

/**
 * Who is using this browser, loaded once per page.
 *
 * The site is public: every visitor reads the same city dataset without a login. Only the
 * review console needs an identity, and the backend decides it (nginx forwards the basic-auth
 * login, and backend/auth.py maps it to a role). This provider is the UI half of that: it hides
 * the console's navigation item from people who cannot use it, and shows them a clear notice
 * instead of a page full of buttons the server would reject.
 *
 * An unreachable /api/auth/me is anonymous, not an error: that is what a crawler or a customer
 * without credentials looks like.
 */
interface IdentityState {
  identity: Identity;
  loading: boolean;
  refresh: () => Promise<void>;
}

const IdentityContext = createContext<IdentityState>({
  identity: ANONYMOUS,
  loading: false,
  refresh: async () => {},
});

export function IdentityProvider({
  children,
  initialIdentity,
}: {
  children: React.ReactNode;
  /** Tests and the imported-dataset demo path pass an identity instead of fetching one. */
  initialIdentity?: Identity;
}) {
  const [identity, setIdentity] = useState<Identity>(initialIdentity ?? ANONYMOUS);
  const [loading, setLoading] = useState(!initialIdentity);
  const mounted = useRef(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const next = await loadIdentity();
      if (mounted.current) setIdentity(next);
    } catch {
      if (mounted.current) setIdentity(ANONYMOUS);
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    if (!initialIdentity) void refresh();
    return () => {
      mounted.current = false;
    };
    // initialIdentity is a mount-time seed; a later change is intentional only in tests.
  }, [initialIdentity, refresh]);

  const value = useMemo(
    () => ({ identity, loading, refresh }),
    [identity, loading, refresh],
  );
  return (
    <IdentityContext.Provider value={value}>{children}</IdentityContext.Provider>
  );
}

export function useIdentity(): IdentityState {
  return useContext(IdentityContext);
}

export { canReview, isAdmin };
export type { Identity };
