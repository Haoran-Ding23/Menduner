import { lazy, type ComponentType } from "react";

/**
 * A lazy import that survives a deploy.
 *
 * Vite fingerprints every chunk. A browser session that started before a deploy is holding an
 * index.html naming the previous hashes; when the user navigates to another page, the dynamic
 * import requests a file that no longer exists, and the page dies with
 * "Unable to preload CSS for /assets/index-<old>.css" or a chunk 404.
 *
 * Preserving old assets and serving index.html uncached (see nginx-menduner.conf and
 * deploy-frontend.sh) make this rare, but a tab left open across a deploy can still hit it, and
 * the correct response is a reload: the fresh index.html names chunks that exist.
 *
 * The reload happens ONCE per session. Without that guard a genuinely broken chunk would put
 * the page in a reload loop and make the failure impossible to read.
 */
const RELOAD_FLAG = "menduner.chunk-reload";

export function isStaleAssetError(error: unknown): boolean {
  const text = error instanceof Error ? `${error.name} ${error.message}` : String(error);
  return (
    /Unable to preload CSS/i.test(text) ||
    /Loading chunk \d+ failed/i.test(text) ||
    /Loading CSS chunk \d+ failed/i.test(text) ||
    /dynamically imported module/i.test(text) ||
    /Importing a module script failed/i.test(text) ||
    /ChunkLoadError/i.test(text)
  );
}

export function lazyWithReload<T extends ComponentType<unknown>>(
  factory: () => Promise<{ default: T }>,
): ReturnType<typeof lazy<T>> {
  return lazy(async () => {
    try {
      const module = await factory();
      // A successful load means the session is current again, so a future deploy gets its own
      // single retry.
      try {
        window.sessionStorage.removeItem(RELOAD_FLAG);
      } catch {
        /* storage can be unavailable; the guard is an optimisation, not a requirement */
      }
      return module;
    } catch (error) {
      if (!isStaleAssetError(error)) throw error;
      let alreadyTried = "1";
      try {
        alreadyTried = window.sessionStorage.getItem(RELOAD_FLAG) ?? "";
      } catch {
        /* fall through: treat as not yet tried */
      }
      if (alreadyTried) throw error;
      try {
        window.sessionStorage.setItem(RELOAD_FLAG, "1");
      } catch {
        /* if the guard cannot be stored, still reload — a loop is the lesser evil to a blank page */
      }
      window.location.reload();
      // Never resolves; the reload takes over. Returning a pending promise keeps React from
      // rendering an error while the navigation is in flight.
      return await new Promise<never>(() => {});
    }
  });
}
