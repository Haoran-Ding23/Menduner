import { useState } from "react";
import { Alert, Button, Card, Col, Form, Input, InputNumber, Modal, Row, Space, Table, Tag } from "antd";
import { Link, useNavigate } from "react-router-dom";
import { useAccount, useEntitlements } from "../../hooks/useEntitlements";
import {
  FEATURES,
  PLANS,
  PLAN_LABELS,
  planAtLeast,
  type FeatureRow,
  type PlanId,
} from "../../services/plans";
import { requestActivation, statusLabel, type CustomerOrder } from "../../services/account";

const STATUS_COLOR: Record<FeatureRow["status"], string> = {
  已上线: "green",
  即将上线: "orange",
  后续: "default",
};
const MONTHLY_PRICE: Record<PlanId, number> = { free: 0, pro: 980, enterprise: 780 };
const ORDER_STATUS: Record<CustomerOrder["status"], { label: string; color: string }> = {
  pending: { label: "待确认收款", color: "orange" },
  confirmed: { label: "已开通", color: "green" },
  cancelled: { label: "已取消", color: "default" },
};

/**
 * The customer-facing plans page, now backed by a real account and a real (offline) payment path.
 *
 * A visitor without an account sees what each tier costs and what it unlocks, and is pointed at
 * invite-code registration. A trial customer can see the trial end date and file a payment
 * request; a paid customer sees the subscription end date. Nothing is unlocked by filling in a
 * request -- the operator confirms the bank transfer first (ReviewConsole -> 客户与开通).
 */
export default function PlansPage() {
  const { state, refresh, logout } = useAccount();
  const { plan, authenticated, label } = useEntitlements();
  const navigate = useNavigate();
  const [modalOpen, setModalOpen] = useState(false);
  const [targetPlan, setTargetPlan] = useState<PlanId>("pro");
  const [months, setMonths] = useState(3);
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  const [orderError, setOrderError] = useState("");

  const account = state.account;
  const pending = state.orders.filter((order) => order.status === "pending");

  const openActivation = (target: PlanId) => {
    setTargetPlan(target);
    setMonths(3);
    setNote("");
    setError("");
    setDone("");
    setModalOpen(true);
  };

  const submitActivation = async () => {
    setSubmitting(true);
    setError("");
    try {
      await requestActivation({ plan: targetPlan, months, note });
      await refresh();
      setModalOpen(false);
      setDone("开通申请已提交。确认到账后会为你开通，可在本页查看订单状态。");
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "提交失败");
    } finally {
      setSubmitting(false);
    }
  };

  const logoutAccount = async () => {
    try {
      await logout();
      setDone("");
    } catch {
      setOrderError("退出失败，请重试");
    }
  };

  const banner = () => {
    if (!authenticated) {
      return (
        <Alert
          type="info"
          showIcon
          message="未登录 · 邀请制试用"
          description="我们通过邀请码开通试用：用邀请码注册后免费体验四周专业版；结束后按对公转账开通正式服务。"
          action={
            <Space direction="vertical">
              <Button type="primary" size="small" onClick={() => navigate("/register")}>
                用邀请码注册
              </Button>
              <Button size="small" onClick={() => navigate("/login")}>
                已有账号登录
              </Button>
            </Space>
          }
        />
      );
    }
    if (account?.status === "suspended") {
      return (
        <Alert type="warning" showIcon message={`账户已暂停 · ${statusLabel(state)}`}
          description="请联系我们恢复账户后再使用付费功能。" />
      );
    }
    if (account?.status === "active") {
      return (
        <Alert
          type="success"
          showIcon
          message={`已开通 · ${label}`}
          description={
            account.subscriptionEndsAt
              ? `服务有效期至 ${formatDate(account.subscriptionEndsAt)}。到期前可提交续费申请。`
              : undefined
          }
          action={
            <Button size="small" onClick={() => openActivation(plan === "free" ? "pro" : plan)}>
              续费
            </Button>
          }
        />
      );
    }
    if (account?.status === "expired") {
      return (
        <Alert
          type="warning"
          showIcon
          message="试用已结束 · 当前为免费版"
          description={
            pending.length
              ? "开通申请已提交，等待确认收款。"
              : "公开活动、来源与证据仍然免费；酒店活动情报、商圈洞察等付费工作流需要开通后使用。"
          }
          action={
            <Button size="small" type="primary" onClick={() => openActivation("pro")}>
              申请开通
            </Button>
          }
        />
      );
    }
    return (
      <Alert
        type="info"
        showIcon
        message={`试用中 · ${label}`}
        description={
          account?.trialEndsAt
            ? `试用有效期至 ${formatDate(account.trialEndsAt)}。结束后可申请开通正式服务。`
            : "试用有效期内可使用专业版工作流。"
        }
        action={
          <Space>
            <Button size="small" type="primary" onClick={() => openActivation(plan === "free" ? "pro" : plan)}>
              申请开通
            </Button>
            <Button size="small" onClick={() => void logoutAccount()}>
              退出登录
            </Button>
          </Space>
        }
      />
    );
  };

  return (
    <>
      <div className="page-heading">
        <div className="eyebrow">服务开通</div>
        <h1>套餐与升级</h1>
        <p>
          公开的活动、来源与证据永久免费；付费解锁的是围绕你的酒店的<strong>工作流</strong>：
          周边筛选、区域对比、周报与变化提醒。<strong>邀请码试用四周，正式服务对公转账开通。</strong>
        </p>
      </div>

      {banner()}
      {done && (
        <Alert className="gap-top" type="success" showIcon message={done} closable
          onClose={() => setDone("")} />
      )}
      {orderError && <Alert className="gap-top" type="error" showIcon message={orderError} />}

      {authenticated && account && (
        <div className="panel gap-top gap-bottom">
          <Space wrap>
            <Tag color="blue">账号 {account.login}</Tag>
            <span>{account.name}</span>
            {account.hotel && <span className="muted">· {account.hotel}</span>}
            <Tag color={account.status === "active" ? "green" : account.status === "trial" ? "gold" : "orange"}>
              {statusLabel(state)}
            </Tag>
            {account.trialEndsAt && account.status === "trial" && (
              <small className="muted">试用至 {formatDate(account.trialEndsAt)}</small>
            )}
            {account.subscriptionEndsAt && account.status === "active" && (
              <small className="muted">订阅至 {formatDate(account.subscriptionEndsAt)}</small>
            )}
            <Button size="small" onClick={() => void logoutAccount()}>
              退出登录
            </Button>
          </Space>
          {state.orders.length > 0 && (
            <Table<CustomerOrder>
              className="gap-top"
              rowKey="id"
              size="small"
              pagination={false}
              dataSource={state.orders}
              columns={[
                { title: "订单号", dataIndex: "id", width: 200 },
                { title: "套餐", dataIndex: "plan", render: (value: PlanId) => PLAN_LABELS[value] },
                { title: "时长", dataIndex: "months", render: (value: number) => `${value} 个月` },
                {
                  title: "金额",
                  dataIndex: "amountCny",
                  render: (value: number) => `¥${value.toLocaleString("zh-CN")}`,
                },
                {
                  title: "状态",
                  dataIndex: "status",
                  render: (value: CustomerOrder["status"]) => (
                    <Tag color={ORDER_STATUS[value].color}>{ORDER_STATUS[value].label}</Tag>
                  ),
                },
                {
                  title: "提交时间",
                  dataIndex: "createdAt",
                  render: (value: string) => formatDate(value),
                },
              ]}
            />
          )}
        </div>
      )}

      <Row gutter={[16, 16]} className="gap-bottom">
        {PLANS.map((card) => {
          const current = card.id === plan;
          const freeCard = card.id === "free";
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
                style={{ height: "100%" }}
                actions={[
                  current ? (
                    <Button key="current" disabled>
                      当前套餐
                    </Button>
                  ) : freeCard ? (
                    <Button key="free" disabled>
                      已包含
                    </Button>
                  ) : (
                    <Button
                      key={card.id}
                      type={card.recommended ? "primary" : "default"}
                      onClick={() => (authenticated ? openActivation(card.id) : navigate("/register"))}
                    >
                      {authenticated ? `申请开通${PLAN_LABELS[card.id]}` : "注册后开通"}
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
            <h3>怎么开通</h3>
            <small className="muted">邀请制 + 对公转账，没有在线支付；每步都可追溯。</small>
          </Space>
        </div>
        <Space direction="vertical" size={10} style={{ width: "100%" }}>
          <div>
            <strong>1. 邀请码注册，免费试用四周</strong>
            <p className="muted" style={{ margin: "4px 0 0" }}>
              向我们索取邀请码，注册后即开始四周专业版试用（从注册时起算，可看账户页剩余时间）。
            </p>
          </div>
          <div>
            <strong>2. 试用结束前提交开通申请</strong>
            <p className="muted" style={{ margin: "4px 0 0" }}>
              在本页选择套餐和月数提交申请；我们会按对公转账流程提供收款信息与发票，金额按
              专业版 ¥980/酒店/月、企业版 ¥780/酒店/月（多店）计算。
            </p>
          </div>
          <div>
            <strong>3. 确认到账后开通</strong>
            <p className="muted" style={{ margin: "4px 0 0" }}>
              我们确认款项后，服务有效期按购买月数自动延长，订单变为「已开通」；未确认前付费功能保持锁定。
            </p>
          </div>
        </Space>
      </section>

      <section className="panel gap-bottom">
        <div className="panel-heading">
          <Space wrap>
            <h3>能力对照</h3>
            <small className="muted">
              「已上线」现在就能用；「即将上线」在路线图里；公开数据在所有套餐里都完整可见。
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
              render: (_, row) => (
                <Tag color={STATUS_COLOR[row.status]}>
                  {planAtLeast("free", row.minimum) ? row.status : "—"}
                </Tag>
              ),
            },
            {
              title: "专业版",
              width: 130,
              render: (_, row) => (
                <Tag color={STATUS_COLOR[row.status]}>
                  {planAtLeast("pro", row.minimum) ? row.status : "—"}
                </Tag>
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
            <strong>为什么公开数据免费，还要付费？</strong>
            <p className="muted" style={{ margin: "4px 0 0" }}>
              公开数据是我们建立信任的方式：每条活动都能点开来源、看字段证据。付费买的不是数据，
              是省时间的工作流——把上百场活动筛成和你酒店有关的一小份清单，每周告诉你有什么变化，
              并输出可直接转发的周报。
            </p>
          </div>
          <div>
            <strong>怎么开始试用？</strong>
            <p className="muted" style={{ margin: "4px 0 0" }}>
              需要邀请码：向我们索取后打开 <Link to="/register">注册页</Link> 填写，即开始四周专业版
              试用。试用不需要付款。
            </p>
          </div>
          <div>
            <strong>怎么付款？</strong>
            <p className="muted" style={{ margin: "4px 0 0" }}>
              线下对公转账：提交开通申请后我们联系你提供账户信息并开票，确认到账后在此开通；
              没有在线支付，也不会自动扣款。
            </p>
          </div>
          <div>
            <strong>免费版会变窄吗？</strong>
            <p className="muted" style={{ margin: "4px 0 0" }}>
              不会。公开活动、来源链接、字段证据和数据质量说明在所有套餐里完整保留。
            </p>
          </div>
        </Space>
      </section>

      <Modal
        title={`申请开通${PLAN_LABELS[targetPlan]}`}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => void submitActivation()}
        okText="提交申请"
        cancelText="取消"
        confirmLoading={submitting}
      >
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Alert
            type="info"
            showIcon
            message="这是开通申请，不是在线支付"
            description="提交后我们联系你走对公转账；确认到账后服务才开通。"
          />
          {error && <Alert type="error" showIcon message={error} />}
          <Form layout="vertical">
            <Form.Item label="套餐">
              <Input value={PLAN_LABELS[targetPlan]} disabled />
            </Form.Item>
            <Form.Item label="购买月数（1–36）">
              <InputNumber
                min={1}
                max={36}
                value={months}
                onChange={(value) => setMonths(Number(value ?? 1))}
                style={{ width: "100%" }}
              />
            </Form.Item>
            <Form.Item label="开票/联系备注（可选）">
              <Input
                value={note}
                placeholder="公司名称、发票抬头、联系人"
                onChange={(event) => setNote(event.target.value)}
              />
            </Form.Item>
          </Form>
          <div>
            预计金额：
            <strong style={{ marginLeft: 8 }}>
              ¥{(MONTHLY_PRICE[targetPlan] * months).toLocaleString("zh-CN")}
            </strong>
            <small className="muted">
              （{MONTHLY_PRICE[targetPlan].toLocaleString("zh-CN")} / 酒店 / 月 × {months} 个月，
              最终以对公合同为准）
            </small>
          </div>
        </Space>
      </Modal>
    </>
  );
}

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString("zh-CN", { timeZone: "Asia/Shanghai" });
}
