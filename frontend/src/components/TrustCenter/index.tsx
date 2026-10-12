import { Alert, Steps, Tag } from "antd";
import sample from "../../data/trust-demo.json";
export default function TrustCenter() {
  return (
    <section className="panel gap-bottom">
      <div className="panel-heading">
        <h3>Data Provenance · 数据来源链路</h3>
        <Tag color="blue">本地记录</Tag>
      </div>
      <div className="trust-content">
        <Steps
          size="small"
          items={[
            {
              title: "来源",
              description: "保留来源名称与原始链接",
              status: "wait",
            },
            {
              title: "字段记录",
              description: "逐字段保留值与提取方式",
              status: "wait",
            },
            {
              title: "核验状态",
              description: "区分已核验、缺失与冲突",
              status: "wait",
            },
            {
              title: "证据查看",
              description: "查看更新时间和原始来源",
              status: "wait",
            },
          ]}
        />
        <p className="muted gap-top">
          本地数据的来源追溯说明。下方字段表显示当前活动与场馆各自的证据；两者独立核验。
        </p>
        <article className="intelligence-card gap-top">
          <h3>Conflict Review · 日期冲突示例</h3>
          <Tag color="blue">DEMO / Synthetic data · 独立合成场景</Tag>
          <div className="comparison-grid">
            {sample.candidates.map((c) => (
              <div key={c.id}>
                <strong>{c.sourceName}</strong>
                <p>Event Date：{c.value}</p>
                <small className="muted">无真实 URL · 未核验</small>
              </div>
            ))}
          </div>
          <Alert
            type="warning"
            message="Resolution status: Needs review"
            description="保留两个来源值，等待核对原始公告、活动身份和变更记录；尚未选定日期。此示例不修改活动字段。"
          />
        </article>
      </div>
    </section>
  );
}
