import { Tag } from "antd";
import type { Event } from "../../types";
import { usePlatform } from "../../hooks/usePlatform";
import { evidenceSummary } from "../../services/intelligence";
import { effectiveStatus, safeUrl } from "../../utils/data";

/** Date and time to the minute. The seconds and the timezone suffix made the line unreadable
 *  and told a hotel manager nothing they could act on. */
function shortStamp(value: string | null | undefined): string {
  if (!value) return "未知";
  const m = value.match(/^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/);
  return m ? `${m[1]} ${m[2]}` : value.slice(0, 10);
}

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
  // Every source we hold for the event, so each row can name where it points instead of only
  // saying 待核验. Grouped by the question the reader is asking: did the organiser say it, did
  // the venue say it, did a government body say it.
  const officialUrl = summary.eventUrls[0];
  const venueUrl = summary.venueUrls[0];
  const governmentUrl =
    government.map((e) => e.sourceUrl).find((u) => safeUrl(u)) ?? undefined;
  const row = (
    label: string,
    url: string | undefined,
    verified: boolean,
  ) => (
    <div className="evidence-entry-row" key={label}>
      <span className="evidence-entry-label">{label}</span>
      {url ? (
        <a href={url} target="_blank" rel="noreferrer" className="evidence-entry-url">
          {new URL(url).hostname} ↗
        </a>
      ) : (
        <span className="muted">未找到</span>
      )}
      <Tag color={verified ? "green" : "default"} style={{ marginInlineStart: "auto" }}>
        {verified ? "已核验" : "待审核"}
      </Tag>
    </div>
  );
  return (
    <section className="intelligence-card gap-top">
      <h3>证据入口</h3>
      <div className="evidence-entries">
        {row("活动官网", officialUrl, official.length > 0)}
        {row("场馆来源", venueUrl, summary.venueUrls.length > 0)}
        {row("政府来源", governmentUrl, government.length > 0)}
      </div>
      {/* A contact for the venue or the organiser is something the customer often has and we do
          not: their own account manager knows the number. Leaving the field visible tells them
          it can be filled in; it is not editable yet because writes need the tenant model. */}
      <div className="evidence-contact">
        <label className="evidence-entry-label" htmlFor="evidence-contact-input">
          联系电话 / 邮箱
        </label>
        <textarea
          id="evidence-contact-input"
          className="evidence-contact-input"
          rows={2}
          placeholder="每行一个，例如：0512-12345678 或 events@example.com"
          disabled
          title="接入租户权限后开放编辑；现在只登记来自公开来源的联系方式"
        />
        <small className="muted">每行一个。公开来源未提供，可在此补充本店掌握的联系方式。</small>
      </div>
      <small className="muted">最后更新：{shortStamp(summary.updatedAt)}</small>
    </section>
  );
}
