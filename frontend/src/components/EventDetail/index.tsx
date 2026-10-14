import { DemandExplanation } from "../DemandIntelligence";
import EvidenceSummary from "../EvidenceSummary";
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
export default function EventDetail() {
  const { detail, repository, closeEvent, go } = usePlatform();
  const event = detail ? repository.getEventById(detail) : undefined;
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
            items={Object.entries({
              "活动 ID": event.id,
              活动类别: categories[event.category].label,
              开始日期: event.startDate,
              结束日期: event.endDate,
              场馆: venue?.name,
              商圈: district
                ? district.name + (district.demo ? "（演示分组）" : "")
                : null,
              主办方: event.organizer,
              参与人数: event.attendance,
              赞助方: event.sponsor,
              坐标: verifiedCoords(venue?.coordinates)
                ? `${venue.coordinates.lng}, ${venue.coordinates.lat} · GCJ-02`
                : "未核验，不上图",
            }).map(([label, value]) => ({
              key: label,
              label,
              children: valueText(value),
            }))}
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
          {repository.getEvidence(event.id).map((e) => (
            <div className="evidence-row" key={e.id}>
              <strong>{e.field}</strong>
              <Tag color={statusColors[effectiveStatus(e)]}>
                {statusLabels[effectiveStatus(e)]}
              </Tag>
              <span>{valueText(e.value)}</span>
              <small>
                {e.method} · {e.sourceName ?? "来源待核验"}
              </small>
              {e.sourceUrl && (
                <a href={e.sourceUrl} target="_blank" rel="noreferrer">
                  打开原始来源 ↗
                </a>
              )}
            </div>
          ))}
        </>
      )}
    </Drawer>
  );
}
