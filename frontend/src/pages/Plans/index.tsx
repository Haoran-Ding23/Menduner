import { Alert, Button, Card, Col, Row, Space, Table, Tag, message } from "antd";
import { useNavigate } from "react-router-dom";
import { useEntitlements } from "../../hooks/useEntitlements";
import {
  FEATURES,
  PLANS,
  PLAN_LABELS,
  planAtLeast,
  type FeatureRow,
  type PlanId,
} from "../../services/plans";

const STATUS_COLOR: Record<FeatureRow["status"], string> = {
  已上线: "green",
  即将上线: "orange",
  后续: "default",
};

/**
 * The customer-facing plan page: what each tier is for, what it unlocks, and how to upgrade.
 *
 * This is the paid surface, not an internal plan. Two commitments are repeated on the page
 * because they decide whether anyone trusts it: public city data (activities, sources, evidence,
 * quality) stays free, and the paid tiers sell the workflow around it. The upgrade buttons are a
 * labelled DEMO switch — no account or payment exists yet — so nothing here claims money moved.
 */
export default function PlansPage() {
  const { plan, setPlan, label, demo } = useEntitlements();
  const navigate = useNavigate();
  // Scoped message API: the static one needs React 18 internals that this build does not have
  // (antd v5 with React 19 warns about compatibility), and the scoped holder is what the rest of
  // the app already uses.
  const [messageApi, holder] = message.useMessage();

  const unlock = (target: PlanId) => {
    setPlan(target);
    messageApi.success(
      target === "free" ? "已切回免费版(演示)" : `已解锁${PLAN_LABELS[target]}(演示,未收费)`,
    );
  };

  const cell = (row: FeatureRow, target: PlanId) => {
    const included = planAtLeast(target, row.minimum);
    if (!included) return <span className="muted">—</span>;
    return (
      <>
        <Tag color={STATUS_COLOR[row.status]}>{row.status}</Tag>
      </>
    );
  };

  return (
    <>
      {holder}
      <div className="page-heading">
        <div className="eyebrow">服务升级</div>
        <h1>套餐与升级</h1>
        <p>
          公开的活动、来源与证据永久免费;付费解锁的是围绕你的酒店的<strong>工作流</strong>:
          周边筛选、区域对比、周报与变化提醒。
        </p>
      </div>

      <Alert
        className="gap-bottom"
        type="info"
        showIcon
        message={`当前套餐:${label}${demo ? "(演示版)" : ""}`}
        description={
          demo
            ? "演示版说明:解锁按钮只在本机切换套餐状态,没有接入真实支付。真实开通需要账号体系与支付接入,试点酒店可免费体验四期。"
            : undefined
        }
        action={
          plan !== "free" ? (
            <Button size="small" onClick={() => unlock("free")}>
              切回免费版
            </Button>
          ) : (
            <Button size="small" type="primary" onClick={() => unlock("pro")}>
              体验专业版
            </Button>
          )
        }
      />

      <Row gutter={[16, 16]} className="gap-bottom">
        {PLANS.map((card) => {
          const current = card.id === plan;
          const locked = !planAtLeast(plan, card.id) && card.id !== "free";
          return (
            <Col xs={24} md={8} key={card.id}>
              <Card
                title={
                  <Space>
                    <strong>{card.name}</strong>
                    {card.recommended && <Tag color="blue">推荐</Tag>}
                    {current && <Tag color="green">当前套餐</Tag>}
                  </Space>
                }
                bordered
                style={{ height: "100%" }}
                actions={[
                  current ? (
                    <Button key="current" disabled>
                      当前套餐
                    </Button>
                  ) : (
                    <Button
                      key={card.id}
                      type={card.recommended ? "primary" : "default"}
                      onClick={() => unlock(card.id)}
                    >
                      {card.id === "free"
                        ? "切回免费版"
                        : locked
                          ? `演示解锁${PLAN_LABELS[card.id]}`
                          : `切换到${PLAN_LABELS[card.id]}`}
                    </Button>
                  ),
                ]}
              >
                <p className="muted" style={{ marginTop: 0 }}>{card.tagline}</p>
                <div style={{ fontSize: 26, fontWeight: 600 }}>{card.price}</div>
                <div className="muted" style={{ marginBottom: 12 }}>{card.priceNote}</div>
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {card.highlights.map((line) => (
                    <li key={line} style={{ margin: "4px 0" }}>{line}</li>
                  ))}
                </ul>
              </Card>
            </Col>
          );
        })}
      </Row>

      <section className="panel gap-bottom">
        <div className="panel-heading">
          <Space wrap>
            <h3>能力对照</h3>
            <small className="muted">
              「已上线」现在就能用;「即将上线」在路线图里;公开数据在所有套餐里都完整可见。
            </small>
          </Space>
        </div>
        <Table<FeatureRow>
          rowKey="id"
          size="small"
          pagination={false}
          dataSource={FEATURES}
          columns={[
            { title: "能力", dataIndex: "label" },
            {
              title: "免费版",
              width: 130,
              render: (_, row) => cell(row, "free"),
            },
            {
              title: "专业版",
              width: 130,
              render: (_, row) => (
                <>
                  <Tag color={STATUS_COLOR[row.status]}>
                    {planAtLeast("pro", row.minimum) ? row.status : "—"}
                  </Tag>
                  {row.minimum === "pro" && row.note && (
                    <small className="block muted">{row.note}</small>
                  )}
                </>
              ),
            },
            {
              title: "企业版",
              width: 150,
              render: (_, row) => (
                <>
                  <Tag color={STATUS_COLOR[row.status]}>
                    {planAtLeast("enterprise", row.minimum) ? row.status : "—"}
                  </Tag>
                  {row.minimum === "enterprise" && row.note && (
                    <small className="block muted">{row.note}</small>
                  )}
                </>
              ),
            },
          ]}
        />
      </section>

      <section className="panel gap-bottom">
        <div className="panel-heading">
          <h3>常见问题</h3>
        </div>
        <Space direction="vertical" size={10} style={{ width: "100%" }}>
          <div>
            <strong>为什么公开数据免费,还要付费?</strong>
            <p className="muted" style={{ margin: "4px 0 0" }}>
              公开数据是我们建立信任的方式:每条活动都能点开来源、看字段证据。付费买的不是数据,
              是省时间的工作流——把上百场活动筛成和你酒店有关的一小份清单,每周告诉你有什么变化,
              并输出可直接转发的周报。
            </p>
          </div>
          <div>
            <strong>现在能真的付款吗?</strong>
            <p className="muted" style={{ margin: "4px 0 0" }}>
              还不能。当前是演示版,没有账号与支付系统;上面的「解锁」只在本机切换状态,用于看
              功能差异。试点酒店四期免费,结束后再谈价格。
            </p>
          </div>
          <div>
            <strong>专业版和企业版的区别?</strong>
            <p className="muted" style={{ margin: "4px 0 0" }}>
              专业版围绕一家酒店(单店周边筛选 + 商圈洞察 + 周报);企业版按酒店数计费,
              可以多店组合对比、团队共用,后续接入私有经营数据与 API。
            </p>
          </div>
          <div>
            <strong>免费版会变窄吗?</strong>
            <p className="muted" style={{ margin: "4px 0 0" }}>
              不会。公开活动、来源链接、字段证据和数据质量说明在所有套餐里完整保留。
            </p>
          </div>
        </Space>
      </section>

      <Alert
        className="gap-bottom"
        type="warning"
        showIcon
        message="想要真实开通?"
        description="试点期可以免费体验专业版四期(每周 PDF+Excel 周报),结束后再决定是否付费。"
        action={
          <Button size="small" onClick={() => navigate("/hotels")}>
            去看看酒店活动情报
          </Button>
        }
      />
    </>
  );
}
