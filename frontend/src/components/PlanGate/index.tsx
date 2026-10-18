import { Button, Result, Space, Tag } from "antd";
import { useNavigate } from "react-router-dom";
import { useEntitlements } from "../../hooks/useEntitlements";
import { PLAN_LABELS, featureById, type FeatureId } from "../../services/plans";

/**
 * The gate a customer sees when a feature belongs to a higher plan.
 *
 * It states what would unlock it and why the tier exists (the workflow, not the public data),
 * and it says the upgrade is a demo switch in this build. It is not a security boundary: with no
 * customer accounts yet, this is a product demonstration of the paid workflow.
 */
export default function PlanGate({
  feature,
  children,
}: {
  feature: FeatureId;
  children: React.ReactNode;
}) {
  const { has, plan, label } = useEntitlements();
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
            演示版:升级按钮只在本机切换套餐状态,未接入真实支付;试点四期可免费体验。
          </span>
        </Space>
      }
      extra={[
        <Button key="upgrade" type="primary" onClick={() => navigate("/plans")}>
          查看套餐并解锁
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
