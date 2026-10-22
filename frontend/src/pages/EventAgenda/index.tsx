import { useMemo, useState } from "react";
import dayjs from "dayjs";
import { Empty, Segmented, Space, Tag, Tooltip } from "antd";
import { usePlatform } from "../../hooks/usePlatform";
import { categories, dates, statusColors, statusLabels, eventStatus } from "../../utils/data";
import { ImpactTag } from "../../components/DemandIntelligence";
import type { Event } from "../../types";
import Filters from "../../components/Filters";

/**
 * A time-first agenda: what is on today, this week, this month.
 *
 * The other pages are organised by space (map), by grid (calendar) or by relation (graph). A
 * revenue manager usually asks a narrower question first — "what starts today?" — and answering
 * that from a calendar grid means reading twenty cells one at a time.
 *
 * The important distinction here is STARTING versus RUNNING. An exhibition that opened in August
 * and closes in October overlaps today, but it is not news: it has been generating demand for
 * weeks. An event that starts today is the new signal. Mixing the two makes the list read as one
 * undifferentiated block, so each period is split into 今日开始 / 今日进行中.
 */
const RANGES = [
  { key: "day", label: "本日" },
  { key: "week", label: "本周" },
  { key: "month", label: "本月" },
] as const;

type RangeKey = (typeof RANGES)[number]["key"];

export const AGENDA_RANGES = RANGES;

/** Local date. `toISOString()` would return UTC and shift the day either side of midnight. */
export function todayKey(): string {
  return dayjs().format("YYYY-MM-DD");
}

export function rangeFor(key: RangeKey): { start: string; end: string; title: string } {
  const now = dayjs();
  if (key === "day") {
    return { start: now.format("YYYY-MM-DD"), end: now.format("YYYY-MM-DD"), title: "今天" };
  }
  if (key === "week") {
    // Monday-first, matching the calendar page.
    const monday = now.subtract((now.day() + 6) % 7, "day");
    return {
      start: monday.format("YYYY-MM-DD"),
      end: monday.add(6, "day").format("YYYY-MM-DD"),
      title: "本周（周一至周日）",
    };
  }
  const first = now.startOf("month");
  return {
    start: first.format("YYYY-MM-DD"),
    end: first.endOf("month").format("YYYY-MM-DD"),
    title: "本月",
  };
}

export function overlapsRange(event: Event, start: string, end: string): boolean {
  const span = dates(event);
  return !!span && span[0] <= end && span[1] >= start;
}

export function startsInRange(event: Event, start: string, end: string): boolean {
  const span = dates(event);
  return !!span && span[0] >= start && span[0] <= end;
}

/** Sort by start date, then by name so the order is stable between renders. */
function byStart(a: Event, b: Event): number {
  const sa = dates(a)?.[0] ?? "9999";
  const sb = dates(b)?.[0] ?? "9999";
  return sa.localeCompare(sb) || a.name.localeCompare(b.name);
}

/** Split a period into the new signal and the already-running background. */
export function partitionByStart(
  events: Event[],
  start: string,
  end: string,
): { starting: Event[]; running: Event[] } {
  const inRange = events.filter((e) => overlapsRange(e, start, end));
  return {
    starting: inRange.filter((e) => startsInRange(e, start, end)).sort(byStart),
    running: inRange.filter((e) => !startsInRange(e, start, end)).sort(byStart),
  };
}

export default function EventAgenda() {
  const { dataset, filters, go, includePast } = usePlatform();
  const [range, setRange] = useState<RangeKey>("week");

  const events = useMemo(
    () =>
      dataset.events.filter(
        (e) =>
          (filters.includeDemo || !e.demo) &&
          (!filters.district || e.districtId === filters.district) &&
          (!filters.category || e.category === filters.category),
      ),
    [dataset, filters.includeDemo, filters.district, filters.category],
  );

  const { start, end, title } = rangeFor(range);
  const { starting, running } = useMemo(
    () => partitionByStart(events, start, end),
    [events, start, end],
  );

  // Today is the point of the page, so its numbers stay visible even while another period is
  // selected — the question "what is on today?" should never require a click.
  const today = todayKey();
  const { starting: todayStarting, running: todayRunning } = useMemo(
    () => partitionByStart(events, today, today),
    [events, today],
  );

  const openOnMap = (event: Event) => {
    // go() sets the year/month filters from the event's own start date and clears the district
    // and category filters, so the event cannot be hidden by a filter left over from this page.
    // The extra `detail` opens the drawer on arrival, which makes the click land on something
    // specific instead of dropping the user on a map with no context.
    go("/map", event.id, { detail: event.id });
  };

  const section = (
    heading: string,
    hint: string,
    list: Event[],
    accent: string,
  ) => (
    <section className="panel gap-bottom" aria-label={heading}>
      <div className="panel-heading">
        <Space wrap>
          <h3 style={{ margin: 0 }}>{heading}</h3>
          <Tag color={accent}>{list.length}</Tag>
          <small className="muted">{hint}</small>
        </Space>
      </div>
      {list.length ? (
        <ol className="agenda-list">
          {list.map((event, index) => (
            <AgendaRow key={event.id} event={event} index={index + 1} onOpen={openOnMap} />
          ))}
        </ol>
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={`${title}没有${hint}`} />
      )}
    </section>
  );

  return (
    <>
      <div className="page-heading">
        <div className="eyebrow">时间情报</div>
        <h1>活动清单</h1>
        <p>按时间顺序看活动 · 点击任意活动跳转到地图查看位置</p>
      </div>
      <Filters />

      <div className="panel gap-bottom">
        <div className="panel-heading">
          <Space size="large" wrap>
            <div>
              <small className="muted">今天</small>
              <strong className="agenda-big">{today}</strong>
            </div>
            <div>
              <small className="muted">新开始</small>
              <strong className="agenda-big" style={{ color: "#1E8E5A" }}>
                {todayStarting.length}
              </strong>
              <span className="muted"> 条</span>
            </div>
            <div>
              <small className="muted">进行中</small>
              <strong className="agenda-big">{todayRunning.length}</strong>
              <span className="muted"> 条</span>
            </div>
            <Tooltip
              title={
                includePast
                  ? "当前显示全部活动，包括已结束的"
                  : "默认隐藏已结束 30 天以上的活动，可在筛选器里切回"
              }
            >
              <small className="muted">
                {includePast ? "含已结束活动" : "已隐藏已结束活动"}
              </small>
            </Tooltip>
          </Space>
          <Segmented
            value={range}
            onChange={(value) => setRange(value as RangeKey)}
            options={RANGES.map((r) => ({ label: r.label, value: r.key }))}
          />
        </div>
      </div>

      {section("1 · 新开始", "在这段时间内开幕或开演，是新的需求信号", starting, "green")}
      {section("2 · 进行中", "更早开始、这段时间内仍在进行，需求已持续", running, "default")}
    </>
  );
}

function AgendaRow({
  event,
  index,
  onOpen,
}: {
  event: Event;
  index: number;
  onOpen: (event: Event) => void;
}) {
  const { repository } = usePlatform();
  const span = dates(event);
  const venue = repository.getVenues().find((v) => v.id === event.venueId);
  const district = repository
    .getDistricts()
    .find((d) => d.id === event.districtId);
  const plottable = !!event.venueId && !!venue?.coordinates;
  const status = eventStatus(repository.getEvidence(event.id));
  const category = categories[event.category];

  return (
    <li>
      <button
        type="button"
        className="agenda-row"
        onClick={() => onOpen(event)}
        aria-label={`在地图上查看 ${event.name}`}
      >
        <span className="agenda-index">{index}</span>
        <span className="agenda-date">
          {span ? span[0].slice(5) : "待定"}
          {span && span[1] !== span[0] && (
            <small className="block muted">至 {span[1].slice(5)}</small>
          )}
        </span>
        <span className="agenda-main">
          <strong>{event.name}</strong>
          <small className="block muted">
            {venue?.name ?? "场馆待核验"}
            {district ? ` · ${district.name}` : ""}
            {event.demo ? " · DEMO" : ""}
          </small>
        </span>
        <span className="agenda-tags">
          <Tag color={category.color} style={{ color: "#fff" }}>
            {category.label}
          </Tag>
          <Tag color={statusColors[status]}>{statusLabels[status]}</Tag>
          {/* ImpactTag is only informative once the venue can be located. Without coordinates the
              assessment is always UNKNOWN, and a column of identical UNKNOWN tags on every row
              is noise rather than information; the 缺坐标 tag below already says why. */}
          {plottable ? (
            <ImpactTag event={event} />
          ) : (
            <Tooltip title="这个场馆还没有核验坐标，地图上无法定位，需求等级也算不出来，仍可在列表里查看">
              <Tag>缺坐标</Tag>
            </Tooltip>
          )}
        </span>
      </button>
    </li>
  );
}
