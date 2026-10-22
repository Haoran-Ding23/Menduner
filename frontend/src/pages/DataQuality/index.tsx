import { useMemo, useState } from "react";
import { Alert, Button, Input, Select, Space, Table, Tag } from "antd";
import { usePlatform } from "../../hooks/usePlatform";
import TrustCenter from "../../components/TrustCenter";
import CrawlHealth from "../../components/CrawlHealth";
import VenueEvents from "../../components/VenueEvents";
import {
  effectiveStatus,
  eventStatus,
  statusColors,
  statusLabels,
  valueText,
} from "../../utils/data";
import type { Event, Evidence, Status } from "../../types";

/**
 * What this dataset is, how it was sourced, and where it is still weak — for anyone.
 *
 * This page used to mix two audiences: the public explanation of the data (which a paying
 * customer must be able to read before trusting anything) and the internal console that
 * approves claims, merges venues and reads the frontend error log. Splitting them is what lets
 * the console sit behind a role while this page stays open: sources and verification status are
 * the trust argument, so they are the one thing that must NOT be paid for.
 *
 * Everything here comes from public read endpoints — no login, no write, no internal queue.
 */
export default function DataQuality() {
  const { dataset, repository, selected, update } = usePlatform();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  // Quality is reviewed per region. 吴中区 holds 356 events and 太仓 123, so one global
  // percentage hides which part of the city is short of evidence; a region is also the unit a
  // reviewer works in, because its events share sources and venues.
  const [region, setRegion] = useState("");
  // A theatre programmes many events; drilling into a venue's full list is public value
  // (it is dataset browsing, not an internal operation), so it stays on this page.
  const [openVenueId, setOpenVenueId] = useState<string | null>(null);

  const count = (value: Status) =>
    dataset.evidence.filter((e) => effectiveStatus(e) === value).length;

  // The administrative regions a reader can pick, with their own event counts.
  const regions = useMemo(
    () =>
      dataset.districts
        .filter((d) => d.kind === "district" || d.kind === "county_city")
        .map((d) => ({
          ...d,
          events: dataset.events.filter((e) => e.districtId === d.id),
        }))
        .sort((a, b) => b.events.length - a.events.length),
    [dataset.districts, dataset.events],
  );

  const records = dataset.events.filter(
    (e) =>
      (e.name.toLowerCase().includes(search.toLowerCase()) ||
        e.id.includes(search)) &&
      (!region || e.districtId === region) &&
      (!status || eventStatus(repository.getEvidence(e.id)) === status),
  );
  const event = repository.getEventById(selected ?? records[0]?.id ?? "");
  const venue = dataset.venues.find((v) => v.id === event?.venueId);
  const fields = useMemo(() => {
    if (!event) return [] as Evidence[];
    return [
      ...repository.getEvidence(event.id),
      ...(venue ? repository.getEvidence(venue.id) : []),
    ];
  }, [event, venue, repository]);
  const entityVenue =
    venue && fields.some((f) => f.entityId === venue.id) ? venue : null;

  return (
    <>
      <div className="page-heading">
        <div className="eyebrow">可信与溯源</div>
        <h1>数据质量与来源</h1>
        <p>
          公开活动的来源、逐字段证据与核验状态；这里只读，不需要登录。
          需要审核数据的人员请使用「审核台」。
        </p>
      </div>
      <div className="stats-strip">
        <div>
          <small>全部活动</small>
          <strong>{dataset.events.length}</strong>
        </div>
        <div>
          <small>核验字段（含场馆/酒店）</small>
          <strong>{count("Verified")}</strong>
        </div>
        <div>
          <small>缺失字段</small>
          <strong>{count("Missing")}</strong>
        </div>
        <div>
          <small>待复核 / 冲突</small>
          <strong>{count("Needs Review") + count("Conflicting")}</strong>
        </div>
      </div>
      <Alert
        className="gap-bottom"
        showIcon
        type="info"
        message={`最后更新：${dataset.updatedAt} · 自动核验规则：官方政府/场馆来源 + 确定性提取才标记「已核验」；聚合站与规则推测的值一律进入人工审核。缺少来源 URL 的已核验字段自动降为待复核。`}
      />
      <TrustCenter />
      <section className="panel gap-bottom" aria-label="采集来源状态">
        <CrawlHealth />
      </section>
      <Alert
        className="gap-bottom"
        type="warning"
        showIcon
        message="这份数据的已知边界"
        description={
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            <li>
              没有活动人数、酒店入住率、平均房价、间夜——所以不做需求强弱判断，也不做收入预测。
            </li>
            <li>
              活动类别由规则自动归类，可能存在误判（例如工业展被归为 others、演唱会被归为
              sports）；核验状态以字段级证据为准。
            </li>
            <li>
              同一活动可能在两个来源各有一条记录，尚未合并；以场馆/官方来源那条为准。
            </li>
            <li>覆盖范围是已采集的公开来源，不是全城活动的完整清单。</li>
          </ul>
        }
      />
      {/* Per-region quality, so a reviewer can see which part of the city is short of evidence
          before scrolling a global list of 663 events. Selecting a row scopes the index below. */}
      <section className="panel gap-bottom" aria-label="分地区数据质量">
        <div className="panel-heading">
          <h3 style={{ margin: 0 }}>分地区数据质量</h3>
          <small className="muted">
            {region
              ? `已筛选：${regions.find((r) => r.id === region)?.name ?? ""}，点击标题回到全部地区`
              : "点击任一行，下方索引只显示该地区的活动"}
          </small>
        </div>
        <Table
          rowKey="id"
          size="small"
          dataSource={regions}
          pagination={false}
          onRow={(r) => ({
            onClick: () => setRegion(r.id === region ? "" : r.id),
            style: { cursor: "pointer" },
          })}
          rowClassName={(r) => (r.id === region ? "table-selected" : "")}
          columns={[
            {
              title: "地区",
              render: (_, r) => <strong>{r.name}</strong>,
            },
            {
              title: "活动",
              width: 90,
              align: "right" as const,
              render: (_, r) => r.events.length,
            },
            ...(["Verified", "Needs Review", "Conflicting", "Missing"] as Status[]).map(
              (s) => ({
                title: statusLabels[s],
                width: 110,
                align: "right" as const,
                render: (_: unknown, r: { events: Event[] }) => {
                  const n = r.events.filter(
                    (e) => eventStatus(repository.getEvidence(e.id)) === s,
                  ).length;
                  const share = r.events.length ? n / r.events.length : 0;
                  return (
                    <span style={{ color: n ? statusColors[s] : "#94A3B8" }}>
                      {n}
                      <small className="muted"> {Math.round(share * 100)}%</small>
                    </span>
                  );
                },
              }),
            ),
          ]}
        />
      </section>
      <div className="evidence-layout">
        <section className="panel">
          <div className="panel-heading">
            <h3>活动证据索引</h3>
          </div>
          <Space wrap className="table-filters">
            <Input.Search
              aria-label="搜索活动证据"
              placeholder="搜索活动名称 / ID"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{ width: 230 }}
            />
            <Select
              aria-label="地区"
              value={region}
              onChange={setRegion}
              style={{ width: 160 }}
              options={[
                { label: "全部地区", value: "" },
                ...regions.map((r) => ({ label: r.name, value: r.id })),
              ]}
            />
            <Select
              aria-label="核验状态"
              value={status}
              onChange={setStatus}
              style={{ width: 170 }}
              options={[
                { label: "全部状态", value: "" },
                ...Object.entries(statusLabels).map(([value, label]) => ({
                  value,
                  label,
                })),
              ]}
            />
          </Space>
          <Table<Event>
            rowKey="id"
            dataSource={records}
            pagination={{ pageSize: 7 }}
            onRow={(e) => ({ onClick: () => update({ event: e.id }) })}
            rowClassName={(e) => (e.id === event?.id ? "table-selected" : "")}
            columns={[
              {
                title: "活动",
                dataIndex: "name",
                render: (_, e) => (
                  <div>
                    <strong>{e.name}</strong>
                    <small className="block muted">
                      {e.id} {e.demo ? "· DEMO" : ""}
                    </small>
                  </div>
                ),
              },
              {
                title: "状态",
                render: (_, e) => {
                  const s = eventStatus(repository.getEvidence(e.id));
                  return <Tag color={statusColors[s]}>{statusLabels[s]}</Tag>;
                },
              },
            ]}
          />
        </section>
        <section className="panel">
          <div className="panel-heading">
            <h3>字段证据：{event?.name ?? "未选择活动"}</h3>
          </div>
          {fields.length ? (
            <Table<Evidence>
              rowKey="id"
              dataSource={fields}
              pagination={false}
              scroll={{ x: 620 }}
              columns={[
                {
                  title: "字段 / 实体",
                  width: 140,
                  render: (_, e) => (
                    <>
                      <strong>{e.field}</strong>
                      <small className="block muted">{e.entityId}</small>
                      {entityVenue && e.entityId === entityVenue.id && (
                        <Button
                          type="link"
                          size="small"
                          style={{ padding: 0, height: "auto" }}
                          onClick={() => setOpenVenueId(entityVenue.id)}
                        >
                          查看该场馆全部活动
                        </Button>
                      )}
                    </>
                  ),
                },
                {
                  title: "值",
                  width: 240,
                  render: (_, e) =>
                    Array.isArray(e.value) &&
                    effectiveStatus(e) === "Conflicting" ? (
                      e.value.map((value, i) => (
                        <div key={i}>
                          候选 {i + 1}：{valueText(value)}
                        </div>
                      ))
                    ) : (
                      <span className="value-wrap">{valueText(e.value)}</span>
                    ),
                },
                {
                  title: "核验 / 来源",
                  width: 220,
                  render: (_, e) => (
                    <>
                      <Tag color={statusColors[effectiveStatus(e)]}>
                        {statusLabels[effectiveStatus(e)]}
                      </Tag>
                      {e.decidedBy && (
                        <Tag color={e.decidedBy === "automatic" ? "blue" : "green"}>
                          {e.decidedBy === "automatic"
                            ? "自动核验"
                            : `人工：${e.decidedBy}`}
                        </Tag>
                      )}
                      <small className="block">
                        {e.sourceName ?? "来源待核验"}
                      </small>
                      {e.sourceUrl ? (
                        <a href={e.sourceUrl} target="_blank" rel="noreferrer">
                          原始来源 ↗
                        </a>
                      ) : (
                        <small className="muted">来源待核验</small>
                      )}
                      <small className="block muted">
                        {(e.decidedAt ?? e.updatedAt).slice(0, 10)}
                      </small>
                    </>
                  ),
                },
              ]}
            />
          ) : (
            <Alert
              type="info"
              showIcon
              message="请选择左侧活动查看字段证据"
              description="字段证据是每条数据的来源记录：哪个字段、值是什么、来自哪一页、什么时候核验。"
            />
          )}
        </section>
      </div>
      {openVenueId && (
        <section className="panel gap-bottom">
          <VenueEvents venueId={openVenueId} onClose={() => setOpenVenueId(null)} />
        </section>
      )}
    </>
  );
}
