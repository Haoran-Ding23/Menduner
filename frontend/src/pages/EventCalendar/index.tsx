import RevenueOutlook from "../../components/RevenueOutlook";
import { assessDemand } from "../../services/intelligence";
import { useState } from "react";
import dayjs from "dayjs";
import { Button, Tag, Segmented, Modal, Empty, Space } from "antd";
import { usePlatform } from "../../hooks/usePlatform";
import { overlaps, categories } from "../../utils/data";
import Filters from "../../components/Filters";
import EventCard from "../../components/EventCard";
export default function EventCalendar() {
  const { dataset, filters, update, openEvent } = usePlatform();
  const [mode, setMode] = useState("month");
  const [week, setWeek] = useState(0);
  const [peak, setPeak] = useState<[string, string] | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const month = dayjs(
    `${filters.year}-${String(filters.month).padStart(2, "0")}-01`,
  );
  const start = month.subtract((month.day() + 6) % 7, "day");
  const days = Array.from({ length: mode === "month" ? 42 : 7 }, (_, i) =>
    start.add((mode === "week" ? week * 7 : 0) + i, "day"),
  );
  const events = dataset.events.filter(
    (e) =>
      (filters.includeDemo || !e.demo) &&
      (!filters.district || e.districtId === filters.district) &&
      (!filters.category || e.category === filters.category),
  );
  const onDay = (date: string) => events.filter((e) => overlaps(e, date, date));
  const move = (delta: number) => {
    setWeek(0);
    setPeak(null);
    const m = month.add(delta, "month");
    update({ year: m.year(), month: m.month() + 1 });
  };
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
            <Button aria-label="上个月" onClick={() => move(-1)}>
              ←
            </Button>
            <h3>
              {filters.year} 年 {filters.month} 月
            </h3>
            <Button aria-label="下个月" onClick={() => move(1)}>
              →
            </Button>
          </Space>
          <Space>
            {mode === "week" && (
              <>
                <Button
                  disabled={week === 0}
                  onClick={() => setWeek((v) => v - 1)}
                >
                  上一周
                </Button>
                <span>第 {week + 1} 周</span>
                <Button
                  disabled={week === 5}
                  onClick={() => setWeek((v) => v + 1)}
                >
                  下一周
                </Button>
              </>
            )}
            <Segmented
              value={mode}
              onChange={(v) => {
                setMode(String(v));
                setWeek(0);
              }}
              options={[
                { label: "月视图", value: "month" },
                { label: "周视图", value: "week" },
              ]}
            />
          </Space>
        </div>
        <div className="calendar-grid">
          {["周一", "周二", "周三", "周四", "周五", "周六", "周日"].map((d) => (
            <div className="calendar-head" key={d}>
              {d}
            </div>
          ))}
          {days.map((d) => {
            const date = d.format("YYYY-MM-DD");
            const records = onDay(date);
            return (
              <div
                className={
                  "calendar-day " +
                  (d.month() + 1 !== filters.month ? "outside" : "") +
                  (peak && date >= peak[0] && date <= peak[1]
                    ? " peak-day"
                    : "")
                }
                key={date}
              >
                <div className="day-label">
                  {d.date()} {records.length > 0 && <Tag>{records.length}</Tag>}
                </div>
                {/* Compact cells: a long exhibition repeats in every day it covers, so a tall
                    card per day turned the whole month into the same paragraph fourteen times.
                    Titles only, one line each, and the overflow is a small +N chip rather than
                    a sentence - the day's full list is one click away in the modal. */}
                {records.slice(0, mode === "week" ? 6 : 3).map((e) => {
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
                {records.length > (mode === "week" ? 6 : 3) && (
                  <button
                    type="button"
                    className="calendar-more"
                    onClick={() => setExpanded(date)}
                    aria-label={`还有 ${records.length - (mode === "week" ? 6 : 3)} 条，查看全部`}
                  >
                    +{records.length - (mode === "week" ? 6 : 3)}
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
        {expanded &&
          onDay(expanded).map((e) => <EventCard event={e} key={e.id} />)}
      </Modal>
      {!events.length && (
        <Empty className="gap-top" description="当前筛选没有活动" />
      )}
    </>
  );
}
