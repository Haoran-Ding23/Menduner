import { Button, Space } from "antd";

/**
 * 空状态引导（GPT Round 25 的「空结果提供操作建议」）。
 *
 * 用户原话的痛点：「查不到数据时只有一片空白，没有下一步」。
 * 所以空状态必须同时给：一句人话解释 + 两三个可以立刻点的动作。
 *
 * 注意：不猜数据、不写「暂无数据」这种话，要写清"为什么没有"。
 */
export interface EmptyAction {
  label: string;
  onClick: () => void;
}

export default function EmptyHint({
  title,
  reason,
  actions = [],
}: {
  title: string;
  reason?: string;
  actions?: EmptyAction[];
}) {
  return (
    <div className="empty-hint" role="status">
      <strong>{title}</strong>
      {reason && <p className="muted">{reason}</p>}
      {actions.length > 0 && (
        <Space wrap>
          {actions.map((action) => (
            <Button key={action.label} size="small" onClick={action.onClick}>
              {action.label}
            </Button>
          ))}
        </Space>
      )}
    </div>
  );
}
