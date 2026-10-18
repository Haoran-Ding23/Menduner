import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Empty,
  Input,
  Popconfirm,
  Result,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  message,
} from "antd";
import { usePlatform } from "../../hooks/usePlatform";
import { canReview, useIdentity } from "../../hooks/useIdentity";
import CustomerAdmin from "../../components/CustomerAdmin";
import {
  clearReview,
  checkWholeEvent,
  loadReviewQueue,
  submitReview,
  type ReviewDecision,
} from "../../services/api";
import VenueMaintenance from "../../components/VenueMaintenance";
import ClientErrors from "../../components/ClientErrors";
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
 * Internal review console: approve claims, merge venues, read the error log.
 *
 * Split out of the public "数据质量与来源" page because the two have different audiences and
 * different permissions. This page is gated twice: the UI refuses to render it for an anonymous
 * visitor or a customer (`viewer`) account, and every endpoint it calls is server-side
 * role-checked — the gate here is a courtesy, not the permission.
 */
export default function ReviewConsole() {
  const { dataset, repository, selected, update, openEvent, reloadData } =
    usePlatform();
  const { identity, loading: identityLoading, refresh } = useIdentity();
  const allowed = canReview(identity);
  const [probing, setProbing] = useState(false);
  const probed = useRef(false);

  // A reviewer who has already logged in gets a role from /api/auth/me; a fresh browser may not.
  // This one probe makes the console recoverable: the gated GET is challenged by nginx, the
  // browser asks for the password, and on success we re-read the identity and render the page.
  // It runs at most once per mount so an anonymous visitor is not prompted in a loop, and the
  // spinner is bounded: answering a password dialog can take a while, and the page should open
  // by itself once the answer arrives instead of giving up on the request.
  const probe = useCallback(async () => {
    if (probed.current) return;
    probed.current = true;
    setProbing(true);
    const stopSpinner = setTimeout(() => setProbing(false), 15_000);
    try {
      await loadReviewQueue();
      await refresh();
    } catch {
      /* refused or unanswered: the gate notice below is the result */
    } finally {
      clearTimeout(stopSpinner);
      setProbing(false);
    }
  }, [refresh]);
  useEffect(() => {
    // Only an anonymous visitor gets the challenge-and-recover path. An authenticated account
    // that simply lacks the role is told so instead of being prompted for another password.
    if (!identityLoading && !allowed && !identity.authenticated) void probe();
  }, [identityLoading, allowed, identity.authenticated, probe]);

  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [openVenueId, setOpenVenueId] = useState<string | null>(null);
  const [queueError, setQueueError] = useState("");
  const [decisions, setDecisions] = useState(0);
  // A reviewer name is required so a decision is attributable. Kept in memory only.
  const [reviewer, setReviewer] = useState(() => {
    try {
      return window.localStorage.getItem("menduner.reviewer") ?? "";
    } catch {
      return "";
    }
  });
  const [busy, setBusy] = useState("");
  const canSubmit = reviewer.trim().length > 0;

  // The authenticated account already carries a display name; prefill it so the reviewer does
  // not sign decisions with an empty field (which used to disable every button silently).
  useEffect(() => {
    if (!reviewer.trim() && identity.name) setReviewer(identity.name);
  }, [identity.name, reviewer]);
  useEffect(() => {
    try {
      if (canSubmit) window.localStorage.setItem("menduner.reviewer", reviewer);
    } catch {
      /* Storage may be unavailable (private mode); the name simply will not persist. */
    }
  }, [reviewer, canSubmit]);

  // The decision log is internal too; loading it proves the role works end to end.
  const loadQueue = useCallback(async () => {
    if (!allowed) return;
    try {
      const rows = await loadReviewQueue();
      setDecisions(rows.length);
      setQueueError("");
    } catch (error) {
      setQueueError(error instanceof Error ? error.message : "读取审核记录失败");
    }
  }, [allowed]);
  useEffect(() => {
    void loadQueue();
  }, [loadQueue]);

  const review = async (
    eventId: string,
    field: string,
    decision: ReviewDecision,
    detail: { value?: unknown; correctedValue?: unknown; note?: string } = {},
  ) => {
    if (!reviewer.trim()) {
      message.warning("请先填写审核人，审核决定需要可追溯");
      return;
    }
    setBusy(`${eventId}:${field}`);
    try {
      await submitReview({ eventId, field, decision, reviewer: reviewer.trim(), ...detail });
      await reloadData();
      await loadQueue();
      message.success(`已记录：${field} → ${decision}`);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "审核提交失败");
    } finally {
      setBusy("");
    }
  };
  const checkAll = async (eventId: string) => {
    if (!canSubmit) {
      message.warning("请先填写审核人姓名");
      return;
    }
    setBusy(`${eventId}:__all__`);
    try {
      const result = await checkWholeEvent({ eventId, reviewer: reviewer.trim() });
      await reloadData();
      await loadQueue();
      const parts = [
        `已核验 ${result.settled} 个字段`,
        result.confirmed_absent.length
          ? `其中 ${result.confirmed_absent.length} 个确认来源无值`
          : "",
        result.conflicts_left_for_manual_review.length
          ? `；${result.conflicts_left_for_manual_review.length} 个冲突字段需单独处理`
          : "",
        result.not_applicable.length
          ? `；${result.not_applicable.length} 个派生字段（编号/分类/来源）不需人工核验`
          : "",
      ].filter(Boolean);
      if (result.needs_attention) message.warning(parts.join(""));
      else message.success(parts.join(""));
    } catch (error) {
      message.error(error instanceof Error ? error.message : "全部核查失败");
    } finally {
      setBusy("");
    }
  };
  const withdraw = async (eventId: string, field: string) => {
    setBusy(`${eventId}:${field}`);
    try {
      await clearReview(eventId, field);
      await reloadData();
      await loadQueue();
      message.success(`已撤回：${field}`);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "撤回失败");
    } finally {
      setBusy("");
    }
  };

  if (identityLoading || probing) {
    return (
      <div className="loading-page">
        <Spin size="large" />
      </div>
    );
  }
  if (!allowed) {
    const retry = () => {
      probed.current = false;
      void probe();
    };
    return (
      <Result
        status="403"
        title="审核台需要审核员权限"
        subTitle={
          identity.authenticated
            ? `当前账号 ${identity.login ?? "—"} 的角色是 ${identity.role ?? "未配置"}，只能浏览数据；审核、合并场馆与坐标需要 reviewer 权限。`
            : "当前未登录。审核台只对审核员/管理员开放；浏览器会在请求时弹出认证框。"
        }
        extra={[
          <Button key="retry" type="primary" onClick={retry}>
            重新检查身份
          </Button>,
          <Button key="back" onClick={() => window.location.assign("/evidence")}>
            返回数据质量页
          </Button>,
        ]}
      />
    );
  }

  const records = dataset.events.filter(
    (e) =>
      (e.name.toLowerCase().includes(search.toLowerCase()) ||
        e.id.includes(search)) &&
      (!status || eventStatus(repository.getEvidence(e.id)) === status),
  );
  const event = repository.getEventById(selected ?? records[0]?.id ?? "");
  const venue = dataset.venues.find((v) => v.id === event?.venueId);
  const fields = event
    ? [...repository.getEvidence(event.id), ...(venue ? repository.getEvidence(venue.id) : [])]
    : [];
  const entityVenue =
    venue && fields.some((f) => f.entityId === venue.id) ? venue : null;
  const count = (s: Status) =>
    dataset.evidence.filter((e) => effectiveStatus(e) === s).length;

  return (
    <>
      <div className="page-heading">
        <div className="eyebrow">内部操作</div>
        <h1>审核台</h1>
        <p>
          逐字段核验、合并场馆、录入坐标；所有决定按登录身份记录，写接口由服务端校验角色。
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
        message={`最后更新：${dataset.updatedAt} · 自动核验规则：官方政府/场馆来源 + 确定性提取才标记「已核验」；聚合站与规则推测的值一律进入人工审核。`}
      />
      {queueError && (
        <Alert
          className="gap-bottom"
          showIcon
          type="warning"
          message="审核记录读取失败"
          description={`${queueError}（若角色刚变更，可点右侧重新检查身份）`}
          action={
            <Button size="small" onClick={() => void refresh()}>
              重新检查身份
            </Button>
          }
        />
      )}
      <section className="panel gap-bottom" aria-label="当前身份与审核人">
        <div className="panel-heading">
          <Space wrap>
            <Tag color="blue">
              当前身份：{identity.name ?? identity.login ?? "已登录"}（
              {identity.role === "admin" ? "管理员" : "审核员"}）
            </Tag>
            <Tag color={decisions > 0 ? "green" : "default"}>
              已记录审核 {decisions} 条
            </Tag>
            <Input
              aria-label="审核人"
              placeholder="审核人姓名（必填）"
              status={reviewer.trim() ? undefined : "warning"}
              value={reviewer}
              onChange={(e) => setReviewer(e.target.value)}
              style={{ width: 200 }}
            />
            <small className="muted">
              审核决定写入独立存储，重新采集后依然保留；若字段值发生变化需重新审核。
            </small>
          </Space>
        </div>
        {!reviewer.trim() && (
          <Alert
            className="gap-top"
            type="warning"
            showIcon
            message="请先填写审核人姓名，否则下方「通过 / 驳回 / 修正」按钮不可用。"
          />
        )}
      </section>
      {identity.role === "admin" && <CustomerAdmin />}
      <VenueMaintenance
        reviewer={reviewer}
        onChanged={async () => {
          await reloadData();
        }}
      />
      {openVenueId && (
        <section className="panel gap-bottom">
          <VenueEvents venueId={openVenueId} onClose={() => setOpenVenueId(null)} />
        </section>
      )}
      <section className="panel gap-bottom" aria-label="前端错误">
        <ClientErrors />
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
            {event && (
              <Space>
                <Popconfirm
                  title="确认该活动的全部事实字段？"
                  description="将逐字段记录你已核对（来源无值的字段记为「确认无值」，值保持为空）。派生字段不参与核验。"
                  okText="确认核验"
                  cancelText="取消"
                  onConfirm={() => void checkAll(event.id)}
                >
                  <Button
                    size="small"
                    type="primary"
                    loading={busy === `${event.id}:__all__`}
                    disabled={!canSubmit}
                    title={canSubmit ? "一次核验该活动的全部事实字段" : "请先填写审核人姓名"}
                  >
                    全部核查完毕
                  </Button>
                </Popconfirm>
                <Button size="small" onClick={() => openEvent(event.id)}>
                  活动详情
                </Button>
              </Space>
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
                  title: "值 / 提取方式",
                  dataIndex: "value",
                  width: 240,
                  render: (_, e) => (
                    <>
                      {Array.isArray(e.value) && effectiveStatus(e) === "Conflicting" ? (
                        e.value.map((value, i) => (
                          <div key={i}>
                            候选 {i + 1}：{valueText(value)}
                          </div>
                        ))
                      ) : (
                        <span className="value-wrap">{valueText(e.value)}</span>
                      )}
                      {["Conflicting", "Needs Review"].includes(effectiveStatus(e)) && (
                        <Tag color="orange">核验状态：待复核</Tag>
                      )}
                      <small className="block muted">{e.method}</small>
                      {e.note && <small className="block muted">{e.note}</small>}
                    </>
                  ),
                },
                {
                  title: "核验 / 来源",
                  width: 190,
                  render: (_, e) => (
                    <>
                      <Tag color={statusColors[effectiveStatus(e)]}>
                        {statusLabels[effectiveStatus(e)]}
                      </Tag>
                      {e.decidedBy && (
                        <Tag color={e.decidedBy === "automatic" ? "blue" : "green"}>
                          {e.decidedBy === "automatic" ? "自动核验" : `人工：${e.decidedBy}`}
                        </Tag>
                      )}
                      <small className="block">{e.sourceName ?? "来源待核验"}</small>
                      {e.sourceUrl ? (
                        <a href={e.sourceUrl} target="_blank" rel="noreferrer">
                          原始来源 ↗
                        </a>
                      ) : (
                        <small className="muted">来源待核验</small>
                      )}
                      {e.decidedReason && (
                        <small className="block muted">{e.decidedReason}</small>
                      )}
                      <small className="block muted">
                        {(e.decidedAt ?? e.updatedAt).slice(0, 10)}
                      </small>
                    </>
                  ),
                },
                {
                  title: "审核操作",
                  width: 210,
                  render: (_, e) => {
                    const key = `${e.entityId}:${e.field}`;
                    const isEventClaim = e.entityId === event?.id;
                    if (!isEventClaim)
                      return <small className="muted">场馆/酒店参考值</small>;
                    return (
                      <Space direction="vertical" size={4} className="review-action">
                        <Space size={4} wrap>
                          <Button
                            size="small"
                            type="primary"
                            ghost
                            loading={busy === key}
                            disabled={e.decidedBy === "automatic" || !canSubmit}
                            title={
                              !canSubmit
                                ? "请先填写审核人姓名"
                                : e.decidedBy === "automatic"
                                  ? "该字段已按规则自动核验"
                                  : "确认此值正确"
                            }
                            onClick={() =>
                              void review(e.entityId, e.field, "Verified", { value: e.value })
                            }
                          >
                            通过
                          </Button>
                          <Button
                            size="small"
                            danger
                            loading={busy === key}
                            disabled={!canSubmit}
                            title={canSubmit ? "驳回此值" : "请先填写审核人姓名"}
                            onClick={() =>
                              void review(e.entityId, e.field, "Rejected", {
                                value: e.value,
                                note: "人工审核未通过",
                              })
                            }
                          >
                            驳回
                          </Button>
                          <Button
                            size="small"
                            loading={busy === key}
                            disabled={!canSubmit}
                            title={canSubmit ? "修正此值" : "请先填写审核人姓名"}
                            onClick={() => {
                              const next = window.prompt(
                                `修正 ${e.field} 的值`,
                                valueText(e.value),
                              );
                              if (next === null || next === "") return;
                              void review(e.entityId, e.field, "Corrected", {
                                value: e.value,
                                correctedValue: next,
                                note: "人工修正",
                              });
                            }}
                          >
                            修正
                          </Button>
                          {e.decidedBy && (
                            <Popconfirm
                              title="撤回该审核决定？"
                              onConfirm={() => void withdraw(e.entityId, e.field)}
                            >
                              <Button size="small" type="text">
                                撤回
                              </Button>
                            </Popconfirm>
                          )}
                        </Space>
                      </Space>
                    );
                  },
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
