import { Button, Space, Tag, Tooltip } from "antd";
import { usePlatform } from "../../hooks/usePlatform";
import {
  PHASE_LABELS,
  caliberCounts,
  phaseOf,
  phaseToday,
  type EventPhase,
  type TimeWindow,
} from "../../utils/caliber";
import { eventCoordinates } from "../../utils/data";
import { distinctByCanonical } from "../../utils/dedupe";
import type { Event } from "../../types";

/**
 * 口径条：每个列表页顶部显示同一组事实 —— 时间范围、含不含演示数据、统计的是活动数还是覆盖
 * 天数、有多少活动因为缺少坐标上不了图。
 *
 * 时间窗口由页面传入，因为各页面的时间控件不同（地图按月、清单按周/月）；但**计算方式**只有
 * 一份，来自 utils/caliber，这样同名数字在两个页面上含义一致。
 */
export default function CaliberBar({
  window,
  events,
}: {
  window: TimeWindow;
  events: Event[];
}) {
  const { dataset, filters, update } = usePlatform();
  // 统计按去重后的活动身份算：同一活动被两个来源收录时只算一场，否则口径条上的数字会比
  // 后端去重结果偏高，前后端对不上。
  const identities = distinctByCanonical(events);
  const counts = caliberCounts(window, identities, (event) => !!eventCoordinates(event, dataset));
  // 三类都列，且按「今天」判断：酒店客户要的是"这场活动现在还在不在办"。
  // 用窗口起点判断会把 10 月 2 日就结束的活动算成"进行中"。
  const phaseOrder: EventPhase[] = ["upcoming", "ongoing", "ended"];
  const todayCounts: Record<EventPhase, number> = { upcoming: 0, ongoing: 0, ended: 0 };
  identities.forEach((event) => {
    todayCounts[phaseToday(event)] += 1;
  });

  return (
    <div className="caliber-bar">
      <Space wrap size={10}>
        <span className="caliber-range">
          统计口径：{window.label}
        </span>
        <Tag color={filters.includeDemo ? "orange" : "default"}>
          {filters.includeDemo ? "含演示数据" : "仅真实数据"}
        </Tag>
        <Button
          size="small"
          type={filters.includeDemo ? "primary" : "default"}
          onClick={() => update({ demo: filters.includeDemo ? null : 1 })}
        >
          {filters.includeDemo ? "隐藏演示数据" : "显示演示数据"}
        </Button>
        <Button
          size="small"
          onClick={() =>
            update({ window: null, from: null, to: null, demo: null, district: null, category: null, past: null })
          }
        >
          重置筛选
        </Button>
      </Space>

      <Space wrap size={14} className="caliber-counts">
        <Tooltip title="与所选时间范围有交集的活动条数；同一活动跨多天只算 1 条">
          <span>
            <strong>{counts.activities}</strong> 个活动
          </span>
        </Tooltip>
        <Tooltip title="这些活动在所选范围内实际占用的日历天数；与活动数是两个不同的量">
          <span>
            <strong>{counts.coveredDays}</strong> 个覆盖天
          </span>
        </Tooltip>
        {phaseOrder.map((phase) => (
          <span key={phase} className="caliber-phase">
            {PHASE_LABELS[phase]} {todayCounts[phase]}
          </span>
        ))}
        {counts.withoutCoordinates > 0 && (
          <Tooltip title="这些活动没有已核验坐标，因此只出现在列表里，不会出现在地图上">
            <span className="caliber-warning">坐标缺失未上图 {counts.withoutCoordinates}</span>
          </Tooltip>
        )}
      </Space>
    </div>
  );
}
