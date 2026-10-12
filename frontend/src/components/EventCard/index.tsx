import { ImpactTag } from "../DemandIntelligence";
import { Tag } from "antd";
import type { Event } from "../../types";
import { usePlatform } from "../../hooks/usePlatform";
import {
  categories,
  dates,
  eventStatus,
  statusColors,
  statusLabels,
  effectiveStatus,
} from "../../utils/data";
export default function EventCard({
  event,
  distance,
}: {
  event: Event;
  distance?: number;
}) {
  const { repository, openEvent, selected } = usePlatform();
  const venue = repository.getVenues().find((v) => v.id === event.venueId);
  const c = categories[event.category];
  const status = eventStatus(repository.getEvidence(event.id));
  const d = dates(event);
  const source = repository
    .getEvidence(event.id)
    .find((e) => effectiveStatus(e) === "Verified" && e.sourceUrl);
  return (
    <button
      className={"event-card " + (selected === event.id ? "selected" : "")}
      onClick={() => openEvent(event.id)}
    >
      <span className="event-dot" style={{ background: c.color }} />
      <div>
        <div className="event-name">
          {event.name} {event.demo && <Tag color="blue">DEMO</Tag>}
        </div>
        <div className="event-meta">
          {d ? `${d[0]}${d[1] !== d[0] ? " → " + d[1] : ""}` : "日期待确认"}
        </div>
        <div className="event-meta">
          {venue?.name ?? "场馆待核验"}
          {distance !== undefined && ` · ${distance.toFixed(2)} km`}
        </div>
        {distance !== undefined && (
          <div className="event-meta">
            活动来源：{source?.sourceName ?? "暂无已核验活动来源"}
          </div>
        )}
        <div className="event-tags">
          <ImpactTag event={event} />
          <Tag color={c.color}>{c.label}</Tag>
          <Tag color={statusColors[status]}>{statusLabels[status]}</Tag>
        </div>
      </div>
    </button>
  );
}
