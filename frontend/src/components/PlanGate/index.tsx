import { Button, Result, Space, Tag } from "antd";
import { useNavigate } from "react-router-dom";
import { useEntitlements } from "../../hooks/useEntitlements";
import { PLAN_LABELS, featureById, type FeatureId } from "../../services/plans";

/**
 * The gate a customer sees when a feature belongs to a higher plan.
 *
 * It states what would unlock it and why the tier exists (the workflow, not the public data), and
 * routes the visitor to the right next step: invite-code registration for a visitor without an
 * account, the plans page (trial status + activation request) for a customer whose trial ran out.
 * Not a security boundary on its own: the plan comes from the server-derived account.
 */
export default function PlanGate({
  feature,
  children,
}: {
  feature: FeatureId;
  children: React.ReactNode;
}) {
  const { has, label, authenticated } = useEntitlements();
  const navigate = useNavigate();
  const row = featureById(feature);
  if (has(feature)) return <>{children}</>;
  return (
    <Result
      status="403"
      title={`「${row.label}」属于${PLAN_LABELS[row.minimum]}`}
      subTitle={
        <Space direction="vertical" size={6} style={{ maxWidth: 560 }}>
          <span>
            当前套餐:{label}。公开的活动、来源与证据数据保持免费;付费解锁的是围绕你的酒店的
            工作流(周边筛选、区域对比、周报与变化提醒)。
          </span>
          <span className="muted">
            {authenticated
              ? "当前账号还没有有效的付费期(试用已结束或未开通)。提交开通申请后,由我们确认对公转账并开通。"
              : "本产品采用邀请制:用邀请码注册即可免费试用四周专业版,试用不需要付款。"}
          </span>
        </Space>
      }
      extra={[
        <Button
          key="next"
          type="primary"
          onClick={() => navigate(authenticated ? "/plans" : "/register")}
        >
          {authenticated ? "查看套餐并申请开通" : "用邀请码注册试用"}
        </Button>,
        <Button key="login" onClick={() => navigate("/login")}>
          已有账号登录
        </Button>,
        <Button key="back" onClick={() => navigate("/map")}>
          返回公开活动
        </Button>,
      ]}
    >
      <div style={{ textAlign: "center" }}>
        <Tag color="orange">需要 {PLAN_LABELS[row.minimum]}</Tag>
      </div>
    </Result>
  );
}
