import TrustCenter from "../../components/TrustCenter";
import { useState } from "react";
import { Input, Select, Table, Tag, Button, Alert, Space, Empty } from "antd";
import { usePlatform } from "../../hooks/usePlatform";
import {
  effectiveStatus,
  eventStatus,
  statusColors,
  statusLabels,
  valueText,
} from "../../utils/data";
import type { Event, Evidence, Status } from "../../types";
export default function EvidenceQuality() {
  const { dataset, repository, selected, update, openEvent } = usePlatform();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const records = dataset.events.filter(
    (e) =>
      (e.name.toLowerCase().includes(search.toLowerCase()) ||
        e.id.includes(search)) &&
      (!status || eventStatus(repository.getEvidence(e.id)) === status),
  );
  const event = repository.getEventById(selected ?? records[0]?.id ?? "");
  const venue = dataset.venues.find((v) => v.id === event?.venueId);
  const fields = event
    ? [
        ...repository.getEvidence(event.id),
        ...(venue ? repository.getEvidence(venue.id) : []),
      ]
    : [];
  const count = (s: Status) =>
    dataset.evidence.filter((e) => effectiveStatus(e) === s).length;
  return (
    <>
      <div className="page-heading">
        <div className="eyebrow">TRUST & PROVENANCE</div>
        <h1>
          Evidence & Data Quality <span>证据与数据质量</span>
        </h1>
        <p>
          Reliable & Traceable Data · 逐字段查看值、来源、核验状态与更新时间
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
        message={`最后更新：${dataset.updatedAt} · 本地值不等于核验事实；合成活动字段保持 DEMO / 未核验。缺少来源 URL 的 Verified 字段降为待复核。`}
      />
      <TrustCenter />
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
            <h3>Field-level Evidence · {event?.name ?? "字段证据"}</h3>
            {event && (
              <Button size="small" onClick={() => openEvent(event.id)}>
                活动详情
              </Button>
            )}
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
                  dataIndex: "field",
                  width: 140,
                  render: (_, e) => (
                    <>
                      <strong>{e.field}</strong>
                      <small className="block muted">{e.entityId}</small>
                    </>
                  ),
                },
                {
                  title: "值 / 提取方式",
                  dataIndex: "value",
                  width: 240,
                  render: (_, e) => (
                    <>
                      {Array.isArray(e.value) &&
                      effectiveStatus(e) === "Conflicting" ? (
                        e.value.map((value, i) => (
                          <div key={i}>
                            候选 {i + 1}：{valueText(value)}
                          </div>
                        ))
                      ) : (
                        <span className="value-wrap">{valueText(e.value)}</span>
                      )}
                      {["Conflicting", "Needs Review"].includes(
                        effectiveStatus(e),
                      ) && (
                        <Tag color="orange">
                          Resolution status: Needs review
                        </Tag>
                      )}
                      <small className="block muted">{e.method}</small>
                      {e.note && (
                        <small className="block muted">{e.note}</small>
                      )}
                    </>
                  ),
                },
                {
                  title: "核验 / 来源",
                  width: 170,
                  render: (_, e) => (
                    <>
                      <Tag color={statusColors[effectiveStatus(e)]}>
                        {statusLabels[effectiveStatus(e)]}
                      </Tag>
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
                        {e.updatedAt.slice(0, 10)}
                      </small>
                    </>
                  ),
                },
              ]}
            />
          ) : (
            <Empty description="请选择活动查看字段证据" />
          )}
        </section>
      </div>
    </>
  );
}
