import { Button, Empty, Tag } from "antd";
import type { Event } from "../../types";
import { usePlatform } from "../../hooks/usePlatform";
import {
  businessToday,
  importantEventPeriods,
  upcomingHighEvents,
  shiftDate,
} from "../../services/intelligence";
import { ImpactTag } from "../DemandIntelligence";
export default function RevenueOutlook({
  events,
  onPeriod,
}: {
  events: Event[];
  onPeriod: (start: string, end: string) => void;
}) {
  const { dataset, filters, openEvent } = usePlatform();
  const today = businessToday();
  const periods = importantEventPeriods(events, filters.year, filters.month);
  const upcoming = upcomingHighEvents(events, dataset, today);
  return (
    <div className="outlook-grid gap-bottom">
      <section className="panel">
        <div className="panel-heading">
          <h3>{filters.month}月 Important Event Period · 重要活动时段</h3>
          <Tag color="blue">已记录日历活动</Tag>
        </div>
        <div className="outlook-content">
          {periods.length ? (
            periods.map((p) => (
              <article className="intelligence-card gap-bottom" key={p.start}>
                <Button onClick={() => onPeriod(p.start, p.end)}>
                  {p.start} → {p.end}
                </Button>
                <p>
                  High activity period · 活动密集时段
                  {p.demo && <Tag color="blue">DEMO</Tag>}
                </p>
                <ul className="explanation-list">
                  {p.reasons.map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
                <small className="muted">
                  涉及 {p.eventIds.length} 条记录 · 点击日期查看日历高亮
                </small>
              </article>
            ))
          ) : (
            <Empty description="本月没有符合重叠或多日条件的活动时段" />
          )}
          <small className="block muted">
            按当前商圈、类别和 DEMO 筛选统计；原因相同的连续日期合并。
          </small>
        </div>
      </section>
      <section className="panel">
        <div className="panel-heading">
          <h3>Upcoming Events · Next 30 days</h3>
          <Tag color="red">{upcoming.length} 个 HIGH 关注项</Tag>
        </div>
        <div className="outlook-content">
          <small className="muted">
            北京时间：{today} → {shiftDate(today, 29)}（含进行中活动）
          </small>
          {upcoming.map((event) => (
            <div className="upcoming-row" key={event.id}>
              <Button type="link" onClick={() => openEvent(event.id)}>
                {event.name}
              </Button>
              <ImpactTag event={event} />
              <small className="block muted">
                {event.startDate} → {event.endDate ?? "结束时间待确认"}
              </small>
            </div>
          ))}
          {!upcoming.length && (
            <Empty description="未来30天没有符合条件的 HIGH 活动" />
          )}
        </div>
      </section>
    </div>
  );
}
