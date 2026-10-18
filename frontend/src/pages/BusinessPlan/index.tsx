import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  Input,
  InputNumber,
  Popconfirm,
  Result,
  Select,
  Slider,
  Space,
  Spin,
  Table,
  Tag,
  message,
} from "antd";
import { usePlatform } from "../../hooks/usePlatform";
import { isAdmin, useIdentity } from "../../hooks/useIdentity";
import {
  DEFAULT_PLAN,
  HYPOTHESIS_STATUSES,
  MILESTONE_STATUSES,
  PIPELINE_STAGES,
  annualMargin,
  annualRevenue,
  blendedPrice,
  breakEvenHotels,
  hotelEvidence,
  loadPlan,
  mergePlan,
  monthlyCost,
  pipelineStats,
  projectedPayers,
  savePlan,
  summarizeEvidence,
  type BusinessPlan,
  type Hypothesis,
  type Milestone,
  type PipelineRow,
  type PipelineStage,
  type HypothesisStatus,
  type MilestoneStatus,
} from "../../services/businessPlan";

/**
 * The internal business-plan panel: the commercial plan as a working document, not a slide.
 *
 * Four things it must do honestly:
 *   - keep assumptions (price, cost, conversion) visibly labelled as assumptions;
 *   - show the live market evidence from the dataset next to them, with the 口径, so a number
 *     cannot be mistaken for measured demand;
 *   - track the pilot pipeline (today: everyone is 未接触) and milestone state;
 *   - persist through the admin-only API, recording who saved it.
 *
 * It is admin-only because it contains price assumptions and customer names. The gate here is
 * UI courtesy; the API enforces the role (GET/PUT /plan are admin-only).
 */
export default function BusinessPlanPage() {
  const { dataset, pipelineStatus } = usePlatform();
  const { identity, loading: identityLoading, refresh } = useIdentity();
  const admin = isAdmin(identity);

  const [plan, setPlan] = useState<BusinessPlan | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [savedBy, setSavedBy] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const state = await loadPlan();
      setPlan(state.document ?? structuredClone(DEFAULT_PLAN));
      setSavedAt(state.updatedAt);
      setSavedBy(state.updatedBy);
      setDirty(false);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "读取商业规划失败");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    if (admin) void load();
  }, [admin, load]);

  const update = useCallback((mutate: (draft: BusinessPlan) => void) => {
    setPlan((previous) => {
      if (!previous) return previous;
      const next = structuredClone(previous);
      mutate(next);
      return next;
    });
    setDirty(true);
  }, []);

  const save = async () => {
    if (!plan) return;
    setSaving(true);
    setError("");
    try {
      const state = await savePlan(plan);
      if (state.document) setPlan(state.document);
      setSavedAt(state.updatedAt);
      setSavedBy(state.updatedBy);
      setDirty(false);
      message.success("商业规划已保存");
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const evidence = useMemo(
    () =>
      summarizeEvidence(dataset, {
        revision: pipelineStatus?.revision,
        sources: pipelineStatus?.sources.length,
      }),
    [dataset, pipelineStatus],
  );
  const perHotelEvidence = useMemo(() => {
    const rows: Record<string, ReturnType<typeof hotelEvidence>> = {};
    for (const row of plan?.pipeline ?? []) rows[row.id] = hotelEvidence(dataset, row.hotel);
    return rows;
  }, [dataset, plan?.pipeline]);

  if (identityLoading) {
    return (
      <div className="loading-page">
        <Spin size="large" />
      </div>
    );
  }
  if (!admin) {
    return (
      <Result
        status="403"
        title="商业规划仅管理员可见"
        subTitle={
          identity.authenticated
            ? `当前账号 ${identity.login ?? "—"} 的角色是 ${identity.role ?? "未配置"}。价格假设与试点名单属于内部规划，不对客户或审核员开放。`
            : "当前未登录。请用管理员账号登录；浏览器会在请求时弹出认证框。"
        }
        extra={[
          <Button key="retry" type="primary" onClick={() => void refresh()}>
            重新检查身份
          </Button>,
          <Button key="back" onClick={() => window.location.assign("/evidence")}>
            返回数据质量页
          </Button>,
        ]}
      />
    );
  }
  if (loading || !plan) {
    return (
      <div className="loading-page">
        <Spin size="large" />
      </div>
    );
  }

  const stats = pipelineStats(plan);
  const breakEven = breakEvenHotels(plan);
  const projected = projectedPayers(plan);
  const price = blendedPrice(plan);
  const cost = monthlyCost(plan);
  const margin = annualMargin(plan);

  const patchHypothesis = (id: string, patch: Partial<Hypothesis>) =>
    update((draft) => {
      const row = draft.hypotheses.find((item) => item.id === id);
      if (row) Object.assign(row, patch);
    });
  const patchPipeline = (id: string, patch: Partial<PipelineRow>) =>
    update((draft) => {
      const row = draft.pipeline.find((item) => item.id === id);
      if (row) Object.assign(row, patch);
    });
  const patchMilestone = (id: string, patch: Partial<Milestone>) =>
    update((draft) => {
      const row = draft.milestones.find((item) => item.id === id);
      if (row) Object.assign(row, patch);
    });

  return (
    <>
      <div className="page-heading">
        <div className="eyebrow">内部规划</div>
        <h1>商业规划</h1>
        <p>
          把套餐、价格、成本、试点管道和验证进度放在一张表里:假设是假设,实测是实测,每个数字都能看出出处。
          仅管理员可见。
        </p>
      </div>

      <section className="panel gap-bottom">
        <div className="panel-heading">
          <Space wrap>
            <Button type="primary" loading={saving} disabled={!dirty} onClick={() => void save()}>
              {dirty ? "保存修改" : "已保存"}
            </Button>
            <Popconfirm
              title="恢复为默认假设?"
              description="只影响当前编辑,保存后才会覆盖服务器上的版本。"
              onConfirm={() => {
                setPlan(structuredClone(DEFAULT_PLAN));
                setDirty(true);
              }}
            >
              <Button>恢复默认假设</Button>
            </Popconfirm>
            {dirty && <Tag color="orange">有未保存修改</Tag>}
            <small className="muted">
              {savedAt
                ? `上次保存:${new Date(savedAt).toLocaleString("zh-CN")} · ${savedBy ?? "—"}`
                : "尚未保存过,当前显示默认假设"}
            </small>
          </Space>
        </div>
        {error && <Alert className="gap-top" type="error" showIcon message={error} />}
        <Alert
          className="gap-top"
          type="info"
          showIcon
          message="金额与转化率是规划假设,不是已验证价格;市场证据来自线上数据集,口径见文末。"
        />
      </section>

      <div className="stats-strip">
        <div>
          <small>试点候选</small>
          <strong>{stats.total}</strong>
        </div>
        <div>
          <small>已联系 / 试点中</small>
          <strong>
            {stats.contacted} / {stats.inPilot}
          </strong>
        </div>
        <div>
          <small>已付费</small>
          <strong>{stats.paid}</strong>
        </div>
        <div>
          <small>盈亏平衡酒店数(月)</small>
          <strong>{Number.isFinite(breakEven) ? breakEven : "—"}</strong>
        </div>
        <div>
          <small>场景年化收入</small>
          <strong>¥{Math.round(annualRevenue(plan)).toLocaleString("zh-CN")}</strong>
        </div>
        <div>
          <small>场景年毛利</small>
          <strong>¥{Math.round(margin).toLocaleString("zh-CN")}</strong>
        </div>
      </div>

      <section className="panel gap-bottom">
        <div className="panel-heading">
          <Space wrap>
            <h3>套餐与价格</h3>
            <Tag color="orange">假设</Tag>
            <small className="muted">收费单位:按酒店/月;试点四期免费。</small>
          </Space>
        </div>
        <div className="field-grid">
          <label>
            <small>专业版(元/酒店/月)</small>
            <InputNumber
              min={0}
              step={100}
              value={plan.pricing.proMonthly}
              onChange={(value) =>
                update((draft) => {
                  draft.pricing.proMonthly = Number(value ?? 0);
                })
              }
              style={{ width: "100%" }}
            />
          </label>
          <label>
            <small>企业版(元/酒店/月)</small>
            <InputNumber
              min={0}
              step={100}
              value={plan.pricing.enterpriseMonthly}
              onChange={(value) =>
                update((draft) => {
                  draft.pricing.enterpriseMonthly = Number(value ?? 0);
                })
              }
              style={{ width: "100%" }}
            />
          </label>
          <label>
            <small>试点期数(期)</small>
            <InputNumber
              min={1}
              max={12}
              value={plan.pricing.trialIssues}
              onChange={(value) =>
                update((draft) => {
                  draft.pricing.trialIssues = Number(value ?? 4);
                })
              }
              style={{ width: "100%" }}
            />
          </label>
        </div>
        <Table
          className="gap-top"
          rowKey="feature"
          size="small"
          pagination={false}
          dataSource={TIER_MATRIX}
          columns={[
            { title: "能力", dataIndex: "feature" },
            { title: "免费版", dataIndex: "free", width: 120 },
            { title: "专业版", dataIndex: "pro", width: 150 },
            { title: "企业版", dataIndex: "enterprise", width: 150 },
            {
              title: "状态",
              dataIndex: "state",
              width: 130,
              render: (state: string) => (
                <Tag color={state === "已有" ? "green" : state.startsWith("NEW") ? "orange" : "default"}>
                  {state}
                </Tag>
              ),
            },
          ]}
        />
      </section>

      <section className="panel gap-bottom">
        <div className="panel-heading">
          <Space wrap>
            <h3>单位经济与场景</h3>
            <Tag color="orange">假设</Tag>
            <small className="muted">
              混合单价 ¥{Math.round(price).toLocaleString("zh-CN")} · 月固定成本 ¥
              {cost.toLocaleString("zh-CN")} · 盈亏平衡 = 月成本 ÷ 混合单价
            </small>
          </Space>
        </div>
        <div className="field-grid">
          <label>
            <small>月服务器成本(元)</small>
            <InputNumber
              min={0}
              step={50}
              value={plan.costs.server}
              onChange={(value) =>
                update((draft) => {
                  draft.costs.server = Number(value ?? 0);
                })
              }
              style={{ width: "100%" }}
            />
          </label>
          <label>
            <small>月数据/API 成本(元)</small>
            <InputNumber
              min={0}
              step={50}
              value={plan.costs.data}
              onChange={(value) =>
                update((draft) => {
                  draft.costs.data = Number(value ?? 0);
                })
              }
              style={{ width: "100%" }}
            />
          </label>
          <label>
            <small>月运营人力成本(元,自评)</small>
            <InputNumber
              min={0}
              step={500}
              value={plan.costs.operations}
              onChange={(value) =>
                update((draft) => {
                  draft.costs.operations = Number(value ?? 0);
                })
              }
              style={{ width: "100%" }}
            />
          </label>
          <label>
            <small>场景付费酒店数:{plan.scenarios.paidHotels}</small>
            <Slider
              min={0}
              max={50}
              value={plan.scenarios.paidHotels}
              onChange={(value) =>
                update((draft) => {
                  draft.scenarios.paidHotels = value;
                })
              }
            />
          </label>
          <label>
            <small>企业版占比:{Math.round(plan.scenarios.enterpriseShare * 100)}%</small>
            <Slider
              min={0}
              max={100}
              value={Math.round(plan.scenarios.enterpriseShare * 100)}
              onChange={(value) =>
                update((draft) => {
                  draft.scenarios.enterpriseShare = value / 100;
                })
              }
            />
          </label>
          <label>
            <small>试点转付费率:{Math.round(plan.scenarios.trialConversion * 100)}%</small>
            <Slider
              min={0}
              max={100}
              value={Math.round(plan.scenarios.trialConversion * 100)}
              onChange={(value) =>
                update((draft) => {
                  draft.scenarios.trialConversion = value / 100;
                })
              }
            />
          </label>
        </div>
        <Alert
          className="gap-top"
          type="warning"
          showIcon
          message={`按当前假设:${plan.pipeline.length} 个试点候选 × 转化率 ${Math.round(
            plan.scenarios.trialConversion * 100,
          )}% ≈ ${projected} 家付费;场景年化收入 ¥${Math.round(
            annualRevenue(plan),
          ).toLocaleString("zh-CN")},年毛利 ¥${Math.round(margin).toLocaleString("zh-CN")}。这些都是假设,不是预测。`}
        />
      </section>

      <section className="panel gap-bottom">
        <div className="panel-heading">
          <Space wrap>
            <h3>商业假设与验证状态</h3>
            <Tag color="blue">试点要验证的东西</Tag>
            <Button
              size="small"
              onClick={() =>
                update((draft) => {
                  draft.hypotheses.push({
                    id: `h${Date.now()}`,
                    text: "",
                    how: "",
                    status: "待验证",
                    note: "",
                  });
                })
              }
            >
              新增假设
            </Button>
          </Space>
        </div>
        <Table<Hypothesis>
          rowKey="id"
          size="small"
          pagination={false}
          dataSource={plan.hypotheses}
          columns={[
            {
              title: "假设",
              width: 280,
              render: (_, row) => (
                <Input
                  value={row.text}
                  placeholder="一句话假设"
                  onChange={(event) => patchHypothesis(row.id, { text: event.target.value })}
                />
              ),
            },
            {
              title: "怎么验证",
              width: 240,
              render: (_, row) => (
                <Input
                  value={row.how}
                  placeholder="验证方式"
                  onChange={(event) => patchHypothesis(row.id, { how: event.target.value })}
                />
              ),
            },
            {
              title: "状态",
              width: 120,
              render: (_, row) => (
                <Select
                  value={row.status}
                  style={{ width: "100%" }}
                  options={HYPOTHESIS_STATUSES.map((status) => ({ value: status, label: status }))}
                  onChange={(value: HypothesisStatus) => patchHypothesis(row.id, { status: value })}
                />
              ),
            },
            {
              title: "备注 / 证据",
              render: (_, row) => (
                <Input
                  value={row.note}
                  placeholder="当前证据或缺口"
                  onChange={(event) => patchHypothesis(row.id, { note: event.target.value })}
                />
              ),
            },
            {
              title: "",
              width: 60,
              render: (_, row) => (
                <Popconfirm
                  title="删除这条假设?"
                  onConfirm={() =>
                    update((draft) => {
                      draft.hypotheses = draft.hypotheses.filter((item) => item.id !== row.id);
                    })
                  }
                >
                  <Button size="small" type="text" danger>
                    删除
                  </Button>
                </Popconfirm>
              ),
            },
          ]}
        />
      </section>

      <section className="panel gap-bottom">
        <div className="panel-heading">
          <Space wrap>
            <h3>试点管道</h3>
            <Tag color="green">实测(数据)</Tag>
            <Tag color="orange">人工(状态)</Tag>
            <Button
              size="small"
              onClick={() =>
                update((draft) => {
                  draft.pipeline.push({
                    id: `pl${Date.now()}`,
                    hotel: "",
                    source: "",
                    stage: "未接触",
                    issues: 0,
                    contact: "",
                    nextAction: "",
                    nextDate: "",
                    note: "",
                  });
                })
              }
            >
              新增候选酒店
            </Button>
            <small className="muted">
              已付费 {stats.paid} 家;当前阶段分布可直接用于决定下一步动作。
            </small>
          </Space>
        </div>
        <Table<PipelineRow>
          rowKey="id"
          size="small"
          pagination={false}
          scroll={{ x: 1280 }}
          dataSource={plan.pipeline}
          columns={[
            {
              title: "酒店(数据集名称)",
              width: 210,
              render: (_, row) => (
                <Input
                  value={row.hotel}
                  placeholder="酒店名称"
                  onChange={(event) => patchPipeline(row.id, { hotel: event.target.value })}
                />
              ),
            },
            {
              title: "来源 / 理由",
              width: 190,
              render: (_, row) => (
                <Input
                  value={row.source}
                  placeholder="为什么列进来"
                  onChange={(event) => patchPipeline(row.id, { source: event.target.value })}
                />
              ),
            },
            {
              title: "阶段",
              width: 130,
              render: (_, row) => (
                <Select
                  value={row.stage}
                  style={{ width: "100%" }}
                  options={PIPELINE_STAGES.map((stage) => ({ value: stage, label: stage }))}
                  onChange={(value: PipelineStage) => patchPipeline(row.id, { stage: value })}
                />
              ),
            },
            {
              title: "已交付期数",
              width: 100,
              render: (_, row) => (
                <InputNumber
                  min={0}
                  max={12}
                  value={row.issues}
                  onChange={(value) => patchPipeline(row.id, { issues: Number(value ?? 0) })}
                  style={{ width: "100%" }}
                />
              ),
            },
            {
              title: "联系人",
              width: 140,
              render: (_, row) => (
                <Input
                  value={row.contact}
                  placeholder="姓名/职务"
                  onChange={(event) => patchPipeline(row.id, { contact: event.target.value })}
                />
              ),
            },
            {
              title: "下一步 / 日期",
              width: 220,
              render: (_, row) => (
                <Space direction="vertical" size={4} style={{ width: "100%" }}>
                  <Input
                    value={row.nextAction}
                    placeholder="下一步动作"
                    onChange={(event) => patchPipeline(row.id, { nextAction: event.target.value })}
                  />
                  <Input
                    value={row.nextDate}
                    placeholder="YYYY-MM-DD"
                    onChange={(event) => patchPipeline(row.id, { nextDate: event.target.value })}
                  />
                </Space>
              ),
            },
            {
              title: "周边证据(实测)",
              width: 170,
              render: (_, row) => {
                const hotel = perHotelEvidence[row.id];
                if (!hotel?.matched) {
                  return <small className="muted">{hotel?.note ?? "未匹配"}</small>;
                }
                return (
                  <small>
                    商务类多日 {hotel.businessMultiDay30d ?? 0} 场 · 演出类 {hotel.cultureMultiDay30d ?? 0} 场
                    <br />
                    <span className="muted">{hotel.distanceWindow}</span>
                  </small>
                );
              },
            },
            {
              title: "",
              width: 60,
              render: (_, row) => (
                <Popconfirm
                  title="从管道中删除?"
                  onConfirm={() =>
                    update((draft) => {
                      draft.pipeline = draft.pipeline.filter((item) => item.id !== row.id);
                    })
                  }
                >
                  <Button size="small" type="text" danger>
                    删除
                  </Button>
                </Popconfirm>
              ),
            },
          ]}
        />
      </section>

      <section className="panel gap-bottom">
        <div className="panel-heading">
          <Space wrap>
            <h3>里程碑</h3>
            <Tag color="orange">人工(状态)</Tag>
          </Space>
        </div>
        <Table<Milestone>
          rowKey="id"
          size="small"
          pagination={false}
          dataSource={plan.milestones}
          columns={[
            { title: "编号", dataIndex: "id", width: 80 },
            {
              title: "内容",
              render: (_, row) => (
                <Input
                  value={row.title}
                  onChange={(event) => patchMilestone(row.id, { title: event.target.value })}
                />
              ),
            },
            {
              title: "状态",
              width: 130,
              render: (_, row) => (
                <Select
                  value={row.status}
                  style={{ width: "100%" }}
                  options={MILESTONE_STATUSES.map((status) => ({ value: status, label: status }))}
                  onChange={(value: MilestoneStatus) => patchMilestone(row.id, { status: value })}
                />
              ),
            },
            {
              title: "备注",
              render: (_, row) => (
                <Input
                  value={row.note}
                  onChange={(event) => patchMilestone(row.id, { note: event.target.value })}
                />
              ),
            },
          ]}
        />
      </section>

      <section className="panel gap-bottom">
        <div className="panel-heading">
          <Space wrap>
            <h3>市场证据(实时)</h3>
            <Tag color="green">实测</Tag>
            <small className="muted">
              数据集 revision {evidence.revision || "—"} · 最后更新 {evidence.updatedAt || "—"}
            </small>
          </Space>
        </div>
        <div className="stats-strip">
          <div>
            <small>活动总数</small>
            <strong>{evidence.events}</strong>
          </div>
          <div>
            <small>未来 30 天新开场 / 进行中</small>
            <strong>
              {evidence.startsIn30d} / {evidence.running30d}
            </strong>
          </div>
          <div>
            <small>有活动的场馆 / 酒店</small>
            <strong>
              {evidence.venues} / {evidence.hotels}
            </strong>
          </div>
          <div>
            <small>字段证据</small>
            <strong>{evidence.evidenceRows}</strong>
          </div>
          <div>
            <small>已核验 / 待复核字段</small>
            <strong>
              {evidence.verifiedFields} / {evidence.needsReviewFields}
            </strong>
          </div>
          <div>
            <small>来源 / 周边地点</small>
            <strong>
              {evidence.sources} / {evidence.places}
            </strong>
          </div>
        </div>
        <Alert
          className="gap-top"
          type="info"
          showIcon
          message="口径与边界"
          description={
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              <li>窗口:今天起 30 天(Asia/Shanghai);「新开场」与「已在进行」分开计数,不重复。</li>
              <li>距离:GCJ-02 坐标上的大圆距离,不是道路距离;周边证据取 3 km、持续 2 天以上。</li>
              <li>缺少活动人数、酒店入住率/房价/间夜,所以本页不做需求强弱或收入预测。</li>
              <li>活动类别为爬虫自动归类,未人工复核;演出类单列,不与商务类相加。</li>
            </ul>
          }
        />
      </section>
    </>
  );
}

/** The tier matrix from the design doc, kept next to the editable prices it belongs to. */
const TIER_MATRIX = [
  {
    feature: "公开活动浏览 / 地图 / 来源与证据",
    free: "全部",
    pro: "全部",
    enterprise: "全部",
    state: "已有",
  },
  {
    feature: "酒店周边筛选(半径/日期)",
    free: "可浏览不可保存",
    pro: "1 家酒店",
    enterprise: "多家酒店",
    state: "已有",
  },
  { feature: "关注清单 / 保存视图", free: "—", pro: "✓", enterprise: "✓", state: "NEW" },
  {
    feature: "变化提醒(新活动/改期/取消)",
    free: "—",
    pro: "✓",
    enterprise: "✓",
    state: "NEW(需变化日志)",
  },
  { feature: "周报导出(PDF+Excel)", free: "—", pro: "✓", enterprise: "✓", state: "NEW" },
  { feature: "团队 / 成员 / 岗位", free: "—", pro: "—", enterprise: "✓", state: "NEW" },
  {
    feature: "企业私有数据接入",
    free: "—",
    pro: "—",
    enterprise: "后续",
    state: "暂缓",
  },
];

// mergePlan is exported for tests and for the case where a stored document predates a field.
export { mergePlan };
