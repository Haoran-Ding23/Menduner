import { Tag } from "antd";
import type { Event } from "../../types";
import { usePlatform } from "../../hooks/usePlatform";
import { evidenceSummary } from "../../services/intelligence";
import { effectiveStatus, safeUrl } from "../../utils/data";
export default function EvidenceSummary({ event }: { event: Event }) {
  const { dataset } = usePlatform();
  const summary = evidenceSummary(event, dataset);
  const eventSources = dataset.evidence.filter(
    (e) =>
      e.entityId === event.id &&
      effectiveStatus(e) === "Verified" &&
      safeUrl(e.sourceUrl),
  );
  const official = eventSources.filter(
    (e) => e.sourceRole === "official_organizer",
  );
  const government = eventSources.filter((e) => e.sourceRole === "government");
  return (
    <section className="intelligence-card gap-top">
      <h3>Traceable China-local Intelligence · 证据入口</h3>
      <div className="source-checks">
        <Tag color={official.length ? "green" : "default"}>
          活动官网 {official.length ? "✓" : "待核验"}
        </Tag>
        <Tag color={summary.venueUrls.length ? "green" : "default"}>
          场馆来源 {summary.venueUrls.length ? "✓" : "待核验"}
        </Tag>
        <Tag color={government.length ? "green" : "default"}>
          政府来源 {government.length ? "✓" : "待核验"}
        </Tag>
      </div>
      <p className="muted">
        独立核验活动来源 {summary.eventUrls.length} 个 · 场馆来源{" "}
        {summary.venueUrls.length} 个；场馆来源不证明活动真实发生。
      </p>
      {[...new Set([...summary.eventUrls, ...summary.venueUrls])].map((url) => (
        <a
          className="block source-url"
          key={url}
          href={url}
          target="_blank"
          rel="noreferrer"
        >
          {new URL(url).hostname} ↗
        </a>
      ))}
      <small className="muted">最后更新：{summary.updatedAt ?? "未知"}</small>
    </section>
  );
}
