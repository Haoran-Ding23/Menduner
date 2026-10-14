import { useMemo, useState } from "react";
import { Button, Empty, Space, Table, Tag, Typography } from "antd";
import { usePlatform } from "../../hooks/usePlatform";
import { eventStatus, statusColors, statusLabels } from "../../utils/data";
import type { Event } from "../../types";

/**
 * All events held at one venue.
 *
 * A theatre programmes many events, so a venue is a useful lens on demand: what is on, when,
 * and how well evidenced. Events are listed newest activity first and keep their own
 * verification status, because a venue being known does not verify the events at it.
 */
export default function VenueEvents({
  venueId,
  onClose,
}: {
  venueId: string;
  onClose?: () => void;
}) {
  const { dataset, repository, openEvent } = usePlatform();
  const [showPast, setShowPast] = useState(true);

  const venue = dataset.venues.find((v) => v.id === venueId);
  const events = useMemo(
    () =>
      dataset.events
        .filter((e) => e.venueId === venueId)
        .sort((a, b) => (b.startDate ?? "").localeCompare(a.startDate ?? "")),
    [dataset.events, venueId],
  );
  const today = new Date().toISOString().slice(0, 10);
  const shown = showPast
    ? events
    : events.filter((e) => (e.startDate ?? "") >= today);

  if (!venue) return <Empty description="场馆记录不存在" />;

  const status = (event: Event) =>
    eventStatus(repository.getEvidence(event.id));

  return (
    <div aria-label={`场馆活动 ${venue.name}`}>
      <div className="panel-heading">
        <Space wrap>
          <strong>{venue.name}</strong>
          <Tag color="blue">{events.length} 个活动</Tag>
          {venue.coordinates ? (
            <Tag color="green">坐标已核验</Tag>
          ) : (
            <Tag color="orange">缺坐标</Tag>
          )}
          <small className="muted">{venue.address ?? "地址待核验"}</small>
        </Space>
        <Space>
          <Button size="small" onClick={() => setShowPast((v) => !v)}>
            {showPast ? "只看未来" : "显示全部"}
          </Button>
          {onClose && (
            <Button size="small" onClick={onClose}>
              收起
            </Button>
          )}
        </Space>
      </div>
      {venue.coordinates && (
        <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
          {venue.coordinates.lng}, {venue.coordinates.lat}（{venue.coordinates.system}）
          {venue.coordinates.sourceUrl && (
            <>
              {" · "}
              <a href={venue.coordinates.sourceUrl} target="_blank" rel="noreferrer">
                坐标来源 ↗
              </a>
            </>
          )}
        </Typography.Paragraph>
      )}
      {shown.length ? (
        <Table<Event>
          rowKey="id"
          dataSource={shown}
          size="small"
          pagination={shown.length > 10 ? { pageSize: 10 } : false}
          onRow={(e) => ({ onClick: () => openEvent(e.id) })}
          columns={[
            {
              title: "日期",
              width: 190,
              render: (_, e) => (
                <span>
                  {e.startDate ?? "待确认"}
                  {e.endDate && e.endDate !== e.startDate ? ` → ${e.endDate}` : ""}
                </span>
              ),
            },
            {
              title: "活动",
              dataIndex: "name",
              render: (_, e) => (
                <>
                  <strong>{e.name}</strong>
                  <small className="block muted">
                    {e.category} · {e.id}
                  </small>
                </>
              ),
            },
            {
              title: "核验",
              width: 120,
              render: (_, e) => {
                const s = status(e);
                return <Tag color={statusColors[s]}>{statusLabels[s]}</Tag>;
              },
            },
          ]}
        />
      ) : (
        <Empty description="该场馆暂无活动记录" />
      )}
    </div>
  );
}
