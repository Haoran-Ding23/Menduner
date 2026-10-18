import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Input, InputNumber, Popconfirm, Select, Space, Table, Tag, message } from "antd";
import {
  AdminAuthError,
  cancelOrder,
  confirmOrder,
  createInvite,
  loadAccounts,
  loadInvites,
  loadOrders,
  type AdminAccount,
  type AdminInvite,
  type AdminOrder,
} from "../../services/admin";
import { PLAN_LABELS, type PlanId } from "../../services/plans";

const INVITE_STATUS: Record<AdminInvite["status"], { label: string; color: string }> = {
  open: { label: "可用", color: "green" },
  used: { label: "已用完", color: "default" },
  expired: { label: "已过期", color: "orange" },
};
const ACCOUNT_STATUS: Record<string, { label: string; color: string }> = {
  trial: { label: "试用中", color: "gold" },
  active: { label: "已开通", color: "green" },
  expired: { label: "试用结束", color: "orange" },
  suspended: { label: "已暂停", color: "red" },
  free: { label: "免费版", color: "default" },
};

/**
 * Operator console for the customer side: generate invite codes, see customers and their
 * effective plan, and confirm the offline (对公转账) payments that open a paid period.
 *
 * The admin endpoints are HTTP Basic-protected; the browser answers the challenge with the
 * operator credentials that also opened the review console. Confirming an order is the only
 * action that grants a paid period, and it records who confirmed it.
 */
export default function CustomerAdmin() {
  const [invites, setInvites] = useState<AdminInvite[]>([]);
  const [accounts, setAccounts] = useState<AdminAccount[]>([]);
  const [orders, setOrders] = useState<AdminOrder[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [authNeeded, setAuthNeeded] = useState(false);
  const [plan, setPlan] = useState<PlanId>("pro");
  const [trialDays, setTrialDays] = useState(28);
  const [maxUses, setMaxUses] = useState(1);
  const [note, setNote] = useState("");
  const [creating, setCreating] = useState(false);
  const [lastCode, setLastCode] = useState("");
  const [messageApi, holder] = message.useMessage();

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [nextInvites, nextAccounts, nextOrders] = await Promise.all([
        loadInvites(),
        loadAccounts(),
        loadOrders("pending"),
      ]);
      setInvites(nextInvites);
      setAccounts(nextAccounts);
      setOrders(nextOrders);
      setAuthNeeded(false);
    } catch (loadError) {
      if (loadError instanceof AdminAuthError) {
        setAuthNeeded(true);
      } else {
        setError(loadError instanceof Error ? loadError.message : "读取客户数据失败");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const generate = async () => {
    setCreating(true);
    setError("");
    try {
      const invite = await createInvite({ plan, trialDays, maxUses, note });
      setLastCode(invite.code);
      setNote("");
      messageApi.success("邀请码已生成");
      await load();
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : "生成邀请码失败");
    } finally {
      setCreating(false);
    }
  };

  const copyCode = async (code: string) => {
    try {
      await navigator.clipboard.writeText(code);
      messageApi.success("邀请码已复制");
    } catch {
      messageApi.info(`邀请码:${code}`);
    }
  };

  const confirm = async (orderId: string) => {
    setError("");
    try {
      await confirmOrder(orderId);
      messageApi.success("已确认收款并开通");
      await load();
    } catch (confirmError) {
      setError(confirmError instanceof Error ? confirmError.message : "确认失败");
    }
  };

  const cancel = async (orderId: string) => {
    setError("");
    try {
      await cancelOrder(orderId);
      messageApi.success("申请已取消");
      await load();
    } catch (cancelError) {
      setError(cancelError instanceof Error ? cancelError.message : "取消失败");
    }
  };

  return (
    <section className="panel gap-bottom">
      {holder}
      <div className="panel-heading">
        <Space wrap>
          <h3>客户与开通</h3>
          <Tag color="cyan">管理员</Tag>
          <small className="muted">
            邀请码开试用,确认对公转账后开通;套餐有效期由服务端按日期判定。
          </small>
        </Space>
      </div>
      {authNeeded && (
        <Alert
          className="gap-bottom"
          type="warning"
          showIcon
          message="需要管理员登录"
          description="浏览器会弹出认证框;登录为管理员账号后点这里重试。"
          action={
            <Button size="small" onClick={() => void load()}>
              重试
            </Button>
          }
        />
      )}
      {error && <Alert className="gap-bottom" type="error" showIcon message={error} />}

      <Space wrap className="gap-bottom" align="end">
        <label>
          <small className="block">套餐</small>
          <Select
            style={{ width: 120 }}
            value={plan}
            onChange={(value: PlanId) => setPlan(value)}
            options={[
              { value: "pro", label: PLAN_LABELS.pro },
              { value: "enterprise", label: PLAN_LABELS.enterprise },
            ]}
          />
        </label>
        <label>
          <small className="block">试用天数</small>
          <InputNumber min={1} max={365} value={trialDays} onChange={(value) => setTrialDays(Number(value ?? 28))} />
        </label>
        <label>
          <small className="block">可用次数</small>
          <InputNumber min={1} max={100} value={maxUses} onChange={(value) => setMaxUses(Number(value ?? 1))} />
        </label>
        <label>
          <small className="block">备注</small>
          <Input
            style={{ width: 200 }}
            value={note}
            placeholder="给谁/哪个酒店"
            onChange={(event) => setNote(event.target.value)}
          />
        </label>
        <Button type="primary" loading={creating} onClick={() => void generate()}>
          生成邀请码
        </Button>
        {lastCode && (
          <span>
            新邀请码:<strong>{lastCode}</strong>
            <Button size="small" type="link" onClick={() => void copyCode(lastCode)}>
              复制
            </Button>
          </span>
        )}
      </Space>

      <div className="panel-heading">
        <Space wrap>
          <h4>待确认收款</h4>
          <Tag color="orange">{orders.length}</Tag>
        </Space>
      </div>
      <Table<AdminOrder>
        rowKey="id"
        size="small"
        pagination={false}
        loading={loading}
        dataSource={orders}
        locale={{ emptyText: "没有待确认的开通申请" }}
        columns={[
          { title: "客户", dataIndex: "accountLogin" },
          { title: "酒店", dataIndex: "accountHotel", render: (value: string | null) => value ?? "—" },
          { title: "套餐", dataIndex: "plan", render: (value: PlanId) => PLAN_LABELS[value] },
          { title: "月数", dataIndex: "months" },
          {
            title: "金额",
            dataIndex: "amountCny",
            render: (value: number) => `¥${value.toLocaleString("zh-CN")}`,
          },
          { title: "备注", dataIndex: "note", render: (value: string | null) => value ?? "—" },
          {
            title: "操作",
            render: (_, row) => (
              <Space>
                <Popconfirm
                  title="已确认收到对公转账?"
                  description="确认后该客户的套餐会立即开通/续期。"
                  onConfirm={() => void confirm(row.id)}
                >
                  <Button size="small" type="primary">
                    确认收款开通
                  </Button>
                </Popconfirm>
                <Popconfirm title="取消这条申请?" onConfirm={() => void cancel(row.id)}>
                  <Button size="small" danger>
                    取消
                  </Button>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />

      <div className="panel-heading gap-top">
        <h4>邀请码</h4>
      </div>
      <Table<AdminInvite>
        rowKey="code"
        size="small"
        pagination={false}
        loading={loading}
        dataSource={invites}
        columns={[
          {
            title: "邀请码",
            dataIndex: "code",
            render: (value: string) => (
              <Space>
                <strong>{value}</strong>
                <Button size="small" type="link" onClick={() => void copyCode(value)}>
                  复制
                </Button>
              </Space>
            ),
          },
          { title: "套餐", dataIndex: "plan", render: (value: PlanId) => PLAN_LABELS[value] },
          { title: "试用天数", dataIndex: "trialDays" },
          {
            title: "使用",
            render: (_, row) => `${row.usedCount} / ${row.maxUses}`,
          },
          {
            title: "状态",
            dataIndex: "status",
            render: (value: AdminInvite["status"]) => (
              <Tag color={INVITE_STATUS[value].color}>{INVITE_STATUS[value].label}</Tag>
            ),
          },
          { title: "备注", dataIndex: "note", render: (value: string | null) => value ?? "—" },
          {
            title: "创建",
            dataIndex: "createdAt",
            render: (value: string) => new Date(value).toLocaleDateString("zh-CN"),
          },
        ]}
      />

      <div className="panel-heading gap-top">
        <h4>客户</h4>
      </div>
      <Table<AdminAccount>
        rowKey="id"
        size="small"
        pagination={false}
        loading={loading}
        dataSource={accounts}
        locale={{ emptyText: "还没有客户账号" }}
        columns={[
          { title: "登录名", dataIndex: "login" },
          { title: "称呼", dataIndex: "name" },
          { title: "酒店", dataIndex: "hotel", render: (value: string | null) => value ?? "—" },
          {
            title: "套餐 / 状态",
            render: (_, row) => (
              <Space>
                <Tag color="blue">{PLAN_LABELS[row.plan]}</Tag>
                <Tag color={ACCOUNT_STATUS[row.status]?.color ?? "default"}>
                  {ACCOUNT_STATUS[row.status]?.label ?? row.status}
                </Tag>
              </Space>
            ),
          },
          {
            title: "有效期至",
            render: (_, row) => {
              const value = row.subscriptionEndsAt ?? row.trialEndsAt;
              return value ? new Date(value).toLocaleDateString("zh-CN") : "—";
            },
          },
          { title: "待确认订单", dataIndex: "pendingOrders" },
          {
            title: "最近登录",
            dataIndex: "lastLoginAt",
            render: (value: string | null) => (value ? new Date(value).toLocaleString("zh-CN") : "—"),
          },
        ]}
      />
    </section>
  );
}
