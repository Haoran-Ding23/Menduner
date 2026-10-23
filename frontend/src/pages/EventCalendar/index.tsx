import RevenueOutlook from "../../components/RevenueOutlook";
import { assessDemand, businessToday } from "../../services/intelligence";
import { useState } from "react";
import dayjs from "dayjs";
import { Button, Tag, Segmented, Modal, Empty, Space } from "antd";
import { usePlatform } from "../../hooks/usePlatform";
import { overlaps, categories } from "../../utils/data";
import Filters from "../../components/Filters";
import EventCard from "../../components/EventCard";

/**
 * 活动日历：默认周视图。
 *
 * 周视图回答的是「这周哪天忙」，所以它必须能**连续往前翻**，而不是在一个月的六行格子里跳。
 * 原来的周视图是从当月 1 号所在周开始数第 N 周，跨月就断掉，也不能看上周的延续活动。
 * 现在用锚点日期滚动：上一周 / 下一周 直接跨月，标题显示真实日期区间。
 *
 * 月视图保留，用于看整月的疏密；两种视图共用同一套筛选。
 */
export default function EventCalendar() {
  const { dataset, filters, update, openEvent } = usePlatform();
  const [mode, setMode] = useState<"week" | "month">("week");
  const [anchor, setAnchor] = useState(() => dayjs(businessToday()));
  const [peak, setPeak] = useState<[string, string] | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  const month = dayjs(`${filters.year}-${String(filters.month).padStart(2, "0")}-01`);
  const monthStart = month.subtract((month.day() + 6) % 7, "day");
  // Week view rolls from an anchor date so 上一周/下一周 can cross a month boundary; month view
  // keeps the six-week block that starts with the 1st's week.
  const weekStart = anchor.subtract((anchor.day() + 6) % 7, "day");
  const start = mode === "week" ? weekStart : monthStart;
  const days = Array.from({ length: mode === "week" ? 7 : 42 }, (_, i) => start.add(i, "day"));

  const events = dataset.events.filter(
    (e) =>
      (filters.includeDemo || !e.demo) &&
      (!filters.district || e.districtId === filters.district) &&
      (!filters.category || e.category === filters.category),
  );
  const onDay = (date: string) => events.filter((e) => overlaps(e, date, date));

  const move = (delta: number) => {
    setPeak(null);
    if (mode === "week") {
      setAnchor((current) => current.add(delta * 7, "day"));
      return;
    }
    const m = month.add(delta, "month");
    update({ year: m.year(), month: m.month() + 1 });
  };

  const heading =
    mode === "week"
      ? `${weekStart.format("YYYY年M月D日")} - ${weekStart.add(6, "day").format("M月D日")}`
      : `${filters.year} 年 ${filters.month} 月`;

  return (
    <>
      <div className="page-heading">
        <div className="eyebrow">时间情报</div>
        <h1>活动日历</h1>
        <p>城市活动时间分布 · 查看重叠活动与重要活动时段</p>
      </div>
      <Filters />
      <RevenueOutlook events={events} onPeriod={(a, b) => setPeak([a, b])} />
      {peak && (
        <div className="gap-bottom">
          <Tag color="blue">
            关注 {peak[0]} → {peak[1]}
          </Tag>
          <Button size="small" onClick={() => setPeak(null)}>
            清除时段高亮
          </Button>
        </div>
      )}
      <div className="panel">
        <div className="panel-heading">
          <Space>
            <Button aria-label={mode === "week" ? "上一周" : "上个月"} onClick={() => move(-1)}>
              ←
            </Button>
            <h3>{heading}</h3>
            <Button aria-label={mode === "week" ? "下一周" : "下个月"} onClick={() => move(1)}>
              →
            </Button>
            {mode === "week" && (
              <Button size="small" onClick={() => setAnchor(dayjs(businessToday()))}>
                回到本周
              </Button>
            )}
          </Space>
          <Segmented
            value={mode}
            onChange={(value) => setMode(value as "week" | "month")}
            options={[
              { label: "周视图", value: "week" },
              { label: "月视图", value: "month" },
            ]}
          />
        </div>
        <div className={"calendar-grid" + (mode === "week" ? " calendar-grid-week" : "")}>
          {["周一", "周二", "周三", "周四", "周五", "周六", "周日"].map((d) => (
            <div className="calendar-head" key={d}>
              {d}
            </div>
          ))}
          {days.map((d) => {
            const date = d.format("YYYY-MM-DD");
            const records = onDay(date);
            const visible = mode === "week" ? records.length : 3;
            return (
              <div
                className={
                  "calendar-day " +
                  (mode === "month" && d.month() + 1 !== filters.month ? "outside " : "") +
                  (peak && date >= peak[0] && date <= peak[1] ? " peak-day" : "")
                }
                key={date}
              >
                <div className="day-label">
                  {mode === "week" ? d.format("M月D日") : d.date()}
                  {records.length > 0 && <Tag>{records.length}</Tag>}
                </div>
                {/* Compact cells: a long exhibition repeats in every day it covers, so a tall
                    card per day turned the whole month into the same paragraph fourteen times.
                    Titles only, one line each, and the overflow is a small +N chip rather than
                    a sentence - the day's full list is one click away in the modal. */}
                {records.slice(0, visible).map((e) => {
                  const level = assessDemand(e, dataset).level;
                  return (
                    <button
                      key={e.id}
                      className="calendar-event"
                      aria-label={(e.demo ? "D · " : "") + e.name}
                      title={`关注等级：${level}；${e.startDate ?? "开始日期待核验"} → ${e.endDate ?? "结束日期待核验"}`}
                      style={{ borderLeftColor: categories[e.category].color }}
                      onClick={() => openEvent(e.id)}
                    >
                      <span>
                        {e.demo ? "D · " : ""}
                        {e.name}
                      </span>
                    </button>
                  );
                })}
                {records.length > visible && (
                  <button
                    type="button"
                    className="calendar-more"
                    onClick={() => setExpanded(date)}
                    aria-label={`还有 ${records.length - visible} 条，查看全部`}
                  >
                    +{records.length - visible}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </div>
      <Modal
        open={!!expanded}
        title={expanded + " · 当日活动"}
        onCancel={() => setExpanded(null)}
        footer={null}
      >
        {expanded && onDay(expanded).map((e) => <EventCard event={e} key={e.id} />)}
      </Modal>
      {!events.length && <Empty className="gap-top" description="当前筛选没有活动" />}
    </>
  );
}
