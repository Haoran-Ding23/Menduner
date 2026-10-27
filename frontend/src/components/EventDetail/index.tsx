import { DemandExplanation } from "../DemandIntelligence";
import EvidenceSummary from "../EvidenceSummary";
import { useEffect } from "react";
import { Drawer, Descriptions, Space, Button, Tag, Alert } from "antd";
import { usePlatform } from "../../hooks/usePlatform";
import {
  categories,
  valueText,
  statusLabels,
  statusColors,
  effectiveStatus,
  verifiedCoords,
} from "../../utils/data";
/** The run as one phrase: the range, then how many days it covers. */
function dateRangeText(start: string | null, end: string | null): string {
  if (!start && !end) return "日期待核验";
  if (!start) return "结束 " + end;
  if (!end || end === start) return start;
  const days = Math.floor((Date.parse(end) - Date.parse(start)) / 86400000) + 1;
  return days > 0 ? `${start} 到 ${end}（${days} 天）` : `${start} 到 ${end}`;
}

export default function EventDetail() {
  const { detail, repository, closeEvent, go } = usePlatform();
  const event = detail ? repository.getEventById(detail) : undefined;

  // 只有链接里明确要求（detail=）才允许常驻打开；
  // 否则切换页面后抽屉应当自动收起 —— 用户反馈"点城市活动地图右边还是冒出详情"。
  useEffect(() => {
    if (!detail) return;
    const params = new URLSearchParams(window.location.search);
    if (!params.get("detail")) closeEvent();
    // 只在路径变化时判断一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [window.location.pathname]);
  const venue = repository.getVenues().find((v) => v.id === event?.venueId);
  const district = repository
    .getDistricts()
    .find((d) => d.id === event?.districtId);
  return (
    <Drawer
      title="活动详情"
      width={550}
      open={!!detail}
      onClose={closeEvent}
    >
      {!event ? (
        <Alert type="warning" message="活动不存在或已在导入后移除" />
      ) : (
        <>
          {event.demo && (
            <Alert
              className="gap-bottom"
              type="info"
              showIcon
              message="DEMO：合成活动，用于交互演示"
              description="场馆坐标可独立核验；该活动并非真实活动事实。"
            />
          )}
          <h2>{event.name}</h2>
          <DemandExplanation event={event} />
          <EvidenceSummary event={event} />
          <Descriptions
            column={1}
            bordered
            items={[
              { label: "活动 ID", children: event.id },
              { label: "活动类别", children: categories[event.category].label },
              {
                // One row instead of two, because the reader's question is "how long does this
                // run", and two dates made them subtract in their head.
                label: "活动日期",
                children: dateRangeText(event.startDate, event.endDate),
              },
              { label: "场馆", children: venue?.name ?? "—" },
              {
                label: "商圈",
                children: district
                  ? district.name + (district.demo ? "（演示分组）" : "")
                  : "—",
              },
              { label: "主办方", children: event.organizer ?? "—" },
              { label: "参与人数", children: valueText(event.attendance) },
              { label: "赞助方", children: event.sponsor ?? "—" },
              {
                label: "坐标",
                children: verifiedCoords(venue?.coordinates) ? (
                  // Clickable so the pin can be checked in the map everyone already uses,
                  // instead of asking the reader to copy two decimals by hand.
                  <a
                    href={`https://uri.amap.com/marker?position=${venue.coordinates.lng},${venue.coordinates.lat}&name=${encodeURIComponent(venue.name)}&callnative=0`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {venue.coordinates.lng}, {venue.coordinates.lat} · 在高德地图查看 ↗
                  </a>
                ) : (
                  "未核验，不上图"
                ),
              },
            ]}
          />
          <Space wrap className="gap-top">
            {[
              ["/map", "地图"],
              ["/calendar", "日历"],
              ["/graph", "关系图谱"],
              ["/evidence", "证据"],
            ].map(([path, label]) => (
              <Button key={path} onClick={() => go(path, event.id)}>
                查看{label}
              </Button>
            ))}
          </Space>
          <h3>字段证据</h3>
          {/* Two lines per field, and no extraction-rule name. A hotel's revenue manager is
              asking "where did this come from", not "which parser produced it": the method
              string (explicit_title_keyword_to_category_rule, taicang_culture_labelled_venue_line)
              is internal machinery, and printing it pushed the one useful fact - the publisher
              - behind jargon. So the second line is the source name, linking to the page. */}
          {repository.getEvidence(event.id).map((e) => (
            <div className="evidence-row" key={e.id}>
              <strong>{e.field}</strong>
              <Tag color={statusColors[effectiveStatus(e)]}>
                {statusLabels[effectiveStatus(e)]}
              </Tag>
              <span>{valueText(e.value)}</span>
              <small>
                {e.sourceUrl ? (
                  <a href={e.sourceUrl} target="_blank" rel="noreferrer">
                    {e.sourceName ?? "查看原始来源"} ↗
                  </a>
                ) : (
                  (e.sourceName ?? "来源待核验")
                )}
              </small>
            </div>
          ))}
        </>
      )}
    </Drawer>
  );
}
