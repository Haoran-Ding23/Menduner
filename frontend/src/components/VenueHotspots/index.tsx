import { useMemo, useState } from "react";
import { Empty, Space, Table, Tag, Typography } from "antd";
import { usePlatform } from "../../hooks/usePlatform";
import { categories, venueHotspots, HOTSPOT_MIN } from "../../utils/data";
import VenueEvents from "../VenueEvents";

/**
 * Demand clustered by venue.
 *
 * A hotel reacts to "苏州保利大剧院 has 8 events this month", not to "吴中区 has 92". A venue is
 * also a hard fact in the data — it came from the source page — whereas a business district is
 * an inference from reverse geocoding. Venues at or above HOTSPOT_MIN are flagged as hotspots.
 *
 * Every row is clickable and opens that venue's full event list, so the number is always
 * traceable back to the events behind it.
 */
export default function VenueHotspots() {
  const { dataset, go } = usePlatform();
  const [openVenue, setOpenVenue] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  const rows = useMemo(
    () => venueHotspots(dataset.events, dataset.venues),
    [dataset.events, dataset.venues],
  );
  const hotspots = rows.filter((row) => row.isHotspot);
  const shown = showAll ? rows : hotspots;

  const venue = openVenue ? dataset.venues.find((v) => v.id === openVenue) : null;

  return (
    <section className="panel gap-bottom" aria-label="场馆热点">
      <div className="panel-heading">
        <Space wrap>
          <h3 style={{ margin: 0 }}>场馆热点</h3>
          <Tag color="red">{hotspots.length} 个热点（≥{HOTSPOT_MIN} 场）</Tag>
          <small className="muted">
            按场馆聚合当前筛选下的活动。场馆取自来源页面，不是推断的商圈。
          </small>
        </Space>
        <Space>
          <a onClick={() => setShowAll((v) => !v)}>
            {showAll ? `只看热点（${hotspots.length}）` : `显示全部场馆（${rows.length}）`}
          </a>
        </Space>
      </div>

      {shown.length ? (
        <Table
          rowKey={(row) => row.venue.id}
          dataSource={shown}
          size="small"
          pagination={shown.length > 10 ? { pageSize: 10 } : false}
          onRow={(row) => ({
            onClick: () => setOpenVenue(row.venue.id),
            style: { cursor: "pointer" },
          })}
          columns={[
            {
              title: "场馆",
              render: (_, row) => (
                <>
                  <strong>{row.venue.name}</strong>
                  {!row.venue.coordinates && (
                    <Tag style={{ marginLeft: 6 }} color="default">
                      缺坐标
                    </Tag>
                  )}
                  <small className="block muted">
                    {row.venue.address ?? "地址待核验"}
                  </small>
                </>
              ),
            },
            {
              title: "活动数",
              width: 100,
              sorter: (a, b) => a.count - b.count,
              defaultSortOrder: "descend",
              render: (_, row) => (
                <Space size={4}>
                  <strong style={{ fontSize: 16 }}>{row.count}</strong>
                  {row.isHotspot && <Tag color="red">热点</Tag>}
                </Space>
              ),
            },
            {
              title: "主要类别",
              width: 170,
              render: (_, row) => {
                if (!row.topCategory) return "—";
                const meta = categories[row.topCategory];
                return (
                  <Tag color={meta.color} style={{ color: "#fff" }}>
                    {meta.label} {row.events.filter((e) => e.category === row.topCategory).length}
                  </Tag>
                );
              },
            },
          ]}
        />
      ) : (
        <Empty
          description={`当前筛选下没有场馆达到 ${HOTSPOT_MIN} 场活动`}
        />
      )}

      {venue && (
        <div className="gap-top">
          <VenueEvents venueId={venue.id} onClose={() => setOpenVenue(null)} />
        </div>
      )}

      {!showAll && rows.length > hotspots.length && (
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          另有 {rows.length - hotspots.length} 个场馆的场次少于 {HOTSPOT_MIN} 场，
          点「显示全部场馆」查看；也可以在
          <a
            onClick={(e) => {
              e.preventDefault();
              go("/map");
            }}
            href="/map"
          >
            城市活动地图
          </a>
          上按坐标查看。
        </Typography.Paragraph>
      )}
    </section>
  );
}
