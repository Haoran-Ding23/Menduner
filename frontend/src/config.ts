/**
 * Build-time switches for the site's public shape.
 *
 * FILING_MODE is for the ICP filing review (备案期间): the reviewers must see a non-commercial
 * information site, so the paid tiers, the account entry, the paid pages and the commercial copy
 * are hidden and their routes redirect to the public map. Nothing is deleted -- after the filing
 * is approved, rebuild without VITE_FILING_MODE to bring the commercial surface back.
 *
 * Build (PowerShell):
 *   $env:VITE_FILING_MODE="1"; npx vite build
 *   Remove-Item Env:\VITE_FILING_MODE   # then a plain build restores the normal site
 */
const env = (import.meta as { env?: Record<string, string | undefined> }).env ?? {};

export const FILING_MODE = env.VITE_FILING_MODE === "1";

/** Names shown publicly; the filing name must match what the reviewers see.
 *
 * No city in the name: the product now opens on 太仓 and covers all of 苏州's districts and
 * county-level cities, so calling it 苏州城市活动 would describe a narrower thing than it is.
 */
export const SITE_TAGLINE = FILING_MODE ? "城市活动信息" : "城市活动情报";
export const SITE_SHORT = FILING_MODE ? "城市活动信息" : "城市活动情报";
export const SITE_TITLE = FILING_MODE ? "Menduner · 城市活动信息" : "Menduner · 城市活动情报";
