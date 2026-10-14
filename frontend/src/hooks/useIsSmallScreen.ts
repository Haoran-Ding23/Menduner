import { useEffect, useState } from "react";

/**
 * Whether the viewport is phone-sized.
 *
 * Some components cannot be fixed with CSS because the decision is structural, not visual: a
 * React Flow MiniMap is a 200x150 absolutely-positioned overlay that covers a third of a 390px
 * screen and reports its own measured size back to the library, and the minimap has no value
 * when the whole graph is already on screen. In those cases the element should not be rendered
 * at all.
 *
 * The media query matches the 760px breakpoint in global.css, so the JS and CSS layers agree on
 * where "phone" begins.
 */
const QUERY = "(max-width: 760px)";

export default function useIsSmallScreen(): boolean {
  const [small, setSmall] = useState(() => {
    // Guarded for the SSR/test path where matchMedia may be absent.
    if (typeof window === "undefined" || !window.matchMedia) return false;
    return window.matchMedia(QUERY).matches;
  });

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mql = window.matchMedia(QUERY);
    const onChange = (event: MediaQueryListEvent) => setSmall(event.matches);
    // resize is listened to as well as the media query: some phone browsers only fire one of
    // them when the URL bar collapses, and the two disagreeing causes a stuck layout.
    const onResize = () => setSmall(window.matchMedia(QUERY).matches);
    mql.addEventListener?.("change", onChange);
    window.addEventListener("resize", onResize);
    return () => {
      mql.removeEventListener?.("change", onChange);
      window.removeEventListener("resize", onResize);
    };
  }, []);

  return small;
}
