import { useMemo, useState } from "react";
import { Empty, Input, Segmented, Space, Table, Tag, Tooltip, Button } from "antd";
import { usePlatform } from "../../hooks/usePlatform";
import {
  categories,
  eventsByVenue,
  HOTSPOT_MIN,
  verifiedCoords,
} from "../../utils/data";
import Filters from "../../components/Filters";
import VenueEvents from "../../components/VenueEvents";

/**
 * Venue-first view: which places programme events, and what is on at each.
 *
 * The map answers "where", the agenda answers "when". Neither answers "what is on at the
 * theatre I care about", which is the question the demand side actually asks. The operations
 * lead interviewed on 2026-10-15 runs a hotel in 太仓 and reasoned entirely in venues -
 * "场地", "场地大小", "音乐节在哪个场地" - and described the problem as 官方渠道比较多，信息比较散，
 * 需要一年中的活动归纳好. This page is that aggregation.
 *
 * The venue list is deliberately NOT filtered by month. A venue programmes across the whole
 * window, so scoping the list to one month would hide the very pattern the page exists to
 * show: that 苏州文化艺术中心 programmes a hundred events and 周庄古镇 four. The month filter
 * still applies to the events shown for the selected venue, because there it is a real
 * question. The other filters (district, category) do apply, since they select what counts.
 */
const SORTS = [
  { key: "count", label: "按活动数" },
  { key: "name", label: "按名称" },
  { key: "date", label: "按最近活动" },
] as const;

type SortKey = (typeof SORTS)[number]["key"];

export default function VenueIndex() {
  const { dataset, filters, go, params, update } = usePlatform();
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("count");

  // District and category select which venues count; year and month do not, for the reason
  // above, so this filters by hand rather than reusing filterEvents.
  const scoped = useMemo(
    () =>
      dataset.events.filter(
        (e) =>
          (filters.includeDemo || !e.demo) &&
          (!filters.district || e.districtId === filters.district) &&
          (!filters.category || e.category === filters.category),
      ),
    [dataset.events, filters.includeDemo, filters.district, filters.category],
  );

  const rows = useMemo(
    () => eventsByVenue(scoped, dataset.venues),
    [scoped, dataset.venues],
  );

  const searched = useMemo(() => {
    const text = query.trim();
    if (!text) return rows;
    return rows.filter(
      (row) =>
        row.venue.name.includes(text) ||
        (row.venue.address ?? "").includes(text),
    );
  }, [rows, query]);

  const sorted = useMemo(() => {
    const copy = [...searched];
    if (sort === "name") {
      copy.sort((a, b) => a.venue.name.localeCompare(b.venue.name));
    } else if (sort === "date") {
      // A venue with no dated event sorts last rather than first.
      copy.sort((a, b) =>
        (a.firstDate ?? "9999").localeCompare(b.firstDate ?? "9999"),
      );
    } else {
      copy.sort((a, b) => b.count - a.count || a.venue.name.localeCompare(b.venue.name));
    }
    return copy;
  }, [searched, sort]);

  const selected = params.get("venue");
  const selectedRow = rows.find((row) => row.venue.id === selected);
  const hotspots = rows.filter((row) => row.count >= HOTSPOT_MIN);
  const withoutCoordinates = rows.filter((row) => !row.hasCoordinates).length;

  return (
    <>
      <div className="page-heading">
        <div className="eyebrow">空间情报</div>
        <h1>场馆活动清单</h1>
        <p>按场馆聚合活动 · 选中场馆查看它排的全部活动</p>
      </div>
      <Filters />

      <div className="stats-strip">
        <div>
          <small>有活动的场馆</small>
          <strong>
            {rows.length}
            <span>个</span>
          </strong>
        </div>
        <div>
          <small>当前筛选活动</small>
          <strong>
            {scoped.filter((e) => e.venueId).length}
            <span>条</span>
          </strong>
        </div>
        <div>
          <small>热点场馆（≥{HOTSPOT_MIN} 场）</small>
          <strong>
            {hotspots.length}
            <span>个</span>
          </strong>
        </div>
        <div>
          <Tooltip title="这些场馆的活动不会出现在地图上，因为场馆还没有核验坐标">
            <small>场馆缺坐标</small>
          </Tooltip>
          <strong>
            {withoutCoordinates}
            <span>个</span>
          </strong>
        </div>
      </div>

      <div className="venue-layout">
        <section className="panel" aria-label="场馆清单">
          <div className="panel-heading">
            <Space wrap>
              <h3 style={{ margin: 0 }}>场馆</h3>
              <Tag color="blue">{sorted.length}</Tag>
            </Space>
          </div>
          <Space wrap className="gap-bottom">
            <Input.Search
              allowClear
              aria-label="搜索场馆"
              placeholder="搜索场馆名或地址"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              style={{ width: 260 }}
            />
            <Segmented
              value={sort}
              onChange={(value) => setSort(value as SortKey)}
              options={SORTS.map((s) => ({ label: s.label, value: s.key }))}
            />
          </Space>
          {sorted.length ? (
            <Table
              rowKey={(row) => row.venue.id}
              dataSource={sorted}
              size="small"
              // Selection lives in the URL, so a reviewer can send a link to one venue.
              rowClassName={(row) =>
                row.venue.id === selected ? "venue-row venue-row-active" : "venue-row"
              }
              onRow={(row) => ({
                onClick: () => update({ venue: row.venue.id }),
                style: { cursor: "pointer" },
              })}
              pagination={sorted.length > 15 ? { pageSize: 15, size: "small" } : false}
              columns={[
                {
                  title: "场馆",
                  dataIndex: ["venue", "name"],
                  render: (_: unknown, row) => (
                    <Space direction="vertical" size={0}>
                      <strong>{row.venue.name}</strong>
                      <small className="muted">
                        {row.venue.address ?? "地址待核验"}
                      </small>
                    </Space>
                  ),
                },
                {
                  title: "活动",
                  dataIndex: "count",
                  width: 78,
                  sorter: (a, b) => a.count - b.count,
                  render: (count: number) => (
                    <Tag color={count >= HOTSPOT_MIN ? "red" : "default"}>{count}</Tag>
                  ),
                },
                {
                  title: "主要类别",
                  dataIndex: "topCategory",
                  width: 104,
                  render: (key: string | null) =>
                    key && categories[key as keyof typeof categories] ? (
                      <Tag
                        color={categories[key as keyof typeof categories].color}
                        style={{ color: "#fff" }}
                      >
                        {categories[key as keyof typeof categories].label}
                      </Tag>
                    ) : (
                      <span className="muted">—</span>
                    ),
                },
                {
                  title: "最早活动",
                  dataIndex: "firstDate",
                  width: 106,
                  render: (value: string | null) => value ?? <span className="muted">—</span>,
                },
                {
                  title: "坐标",
                  dataIndex: "hasCoordinates",
                  width: 76,
                  render: (has: boolean) =>
                    has ? (
                      <Tag color="green">已核验</Tag>
                    ) : (
                      <Tooltip title="这个场馆没有核验坐标，它的活动不会出现在地图上">
                        <Tag color="orange">缺坐标</Tag>
                      </Tooltip>
                    ),
                },
              ]}
            />
          ) : (
            <Empty description={query ? `没有匹配「${query}」的场馆` : "当前筛选下没有场馆"} />
          )}
        </section>

        <section className="panel venue-panel" aria-label="场馆活动">
          {selectedRow ? (
            <>
              <VenueEvents
                venueId={selectedRow.venue.id}
                onClose={() => update({ venue: null })}
              />
              <div className="gap-top">
                <Space wrap>
                  {selectedRow.hasCoordinates ? (
                    <Button
                      size="small"
                      onClick={() =>
                        go("/map", selectedRow.events[0]?.id, {
                          venue: selectedRow.venue.id,
                        })
                      }
                    >
                      在地图中查看
                    </Button>
                  ) : (
                    <Tooltip title="这个场馆还没有核验坐标，无法在地图上定位">
                      <Button size="small" disabled>
                        在地图中查看
                      </Button>
                    </Tooltip>
                  )}
                  <Button
                    size="small"
                    onClick={() => go("/graph", selectedRow.events[0]?.id)}
                  >
                    在知识图谱中查看
                  </Button>
                </Space>
              </div>
            </>
          ) : (
            <Empty
              description={
                rows.length
                  ? "从左侧选择一个场馆，查看它排的全部活动"
                  : "当前筛选下没有可展示的场馆"
              }
            />
          )}
        </section>
      </div>
    </>
  );
}
