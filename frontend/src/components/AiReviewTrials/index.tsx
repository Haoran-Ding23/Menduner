import { useCallback, useEffect, useState } from "react";
import { App, Button, Collapse, Space, Table, Tag, Tooltip, message as staticMessage } from "antd";
import {
  generateAiReview,
  labelAiReview,
  loadAiReviewStats,
  loadAiReviewTrials,
  type AiReviewStats,
  type AiReviewTrial,
} from "../../services/api";

/**
 * AI 建议核对（试验台）。
 *
 * 三条红线写在界面上：
 *   1. AI 只提建议，**不改核验状态**（状态只能由人在字段表里点 ✓/✗ 决定）；
 *   2. 每条建议都能看到理由、置信度和证据链接；
 *   3. 人的判定（对/错）会留档：判定人 + 时间 + 备注，用于统计误报率。
 */
const FIELD_LABELS: Record<string, string> = {
  name: "活动名字",
  venueName: "活动场地",
  sourceUrl: "来源链接",
};

const CONFIDENCE_LABELS: Record<string, string> = {
  high: "高",
  medium: "中",
  low: "低",
};

export default function AiReviewTrials({ canReview }: { canReview: boolean }) {
  const appContext = App.useApp();
  const message = appContext?.message ?? staticMessage;
  const [trials, setTrials] = useState<AiReviewTrial[]>([]);
  const [batches, setBatches] = useState<string[]>([]);
  const [batch, setBatch] = useState<string | undefined>(undefined);
  const [stats, setStats] = useState<AiReviewStats | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    // 接口或桩数据可能缺字段：一律给安全默认值，绝不让整个页面因一块试验面板崩掉
    const [list, next] = await Promise.all([loadAiReviewTrials(batch), loadAiReviewStats()]);
    setTrials(Array.isArray(list?.trials) ? list.trials : []);
    setBatches(Array.isArray(list?.batches) ? list.batches : []);
    setStats(next && typeof next.total === "number" ? next : null);
  }, [batch]);

  useEffect(() => {
    void refresh().catch(() => undefined);
  }, [refresh]);

  if (!canReview && trials.length === 0 && !stats) return null;

  const generate = async () => {
    setBusy(true);
    try {
      const result = await generateAiReview(25);
      if (!result.available) {
        message.warning(result.reason ?? "生成不可用");
      } else {
        message.success(
          "已生成 " + result.created + " 条建议（未改动任何核验状态）" +
            ((result.rejected?.length ?? 0) ? "，跳过 " + (result.rejected?.length ?? 0) + " 条" : ""),
        );
      }
      await refresh();
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const label = async (trial: AiReviewTrial, verdict: "agree" | "disagree") => {
    try {
      await labelAiReview(trial.id, verdict);
      message.success(verdict === "agree" ? "已记为：AI 建议正确" : "已记为：AI 建议有误");
      await refresh();
    } catch (error) {
      message.error((error as Error).message);
    }
  };

  return (
    <section className="panel gap-bottom" aria-label="AI 建议核对">
      <div className="panel-heading">
        <h3 style={{ margin: 0 }}>
          AI 建议核对（试验）
          <Tag style={{ marginLeft: 8 }}>AI 只建议 · 不改核验状态</Tag>
        </h3>
        <Space wrap>
          {batches.length > 0 && (
            <select
              className="batch-select"
              value={batch ?? ""}
              onChange={(event) => setBatch(event.target.value || undefined)}
              aria-label="选择批次"
            >
              <option value="">全部批次</option>
              {batches.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          )}
          <Button size="small" disabled={!canReview || busy} loading={busy} onClick={() => void generate()}>
            生成 25 条建议
          </Button>
        </Space>
      </div>

      {stats && (
        <p className="muted" style={{ margin: "0 0 10px" }}>
          共 {stats.total} 条 · 已标注 {stats.labeled} 条 · AI 有误 {stats.disagree} 条 ·{" "}
          误报率 {stats.errorRate === null ? "暂无（还没标注）" : Math.round(stats.errorRate * 100) + "%"} ·{" "}
          {stats.note}
        </p>
      )}

      {trials.length === 0 ? (
        <p className="muted">还没有 AI 建议。点右上「生成 25 条建议」开始（需要审核角色）。</p>
      ) : (
        <Table<AiReviewTrial>
          size="small"
          rowKey="id"
          dataSource={trials}
          pagination={{ pageSize: 10 }}
          columns={[
            { title: "字段", dataIndex: "field", width: 96, render: (value: string) => FIELD_LABELS[value] ?? value },
            {
              title: "现在值",
              dataIndex: "current_value",
              width: 200,
              render: (value: string | null) => <span className="cell-ellipsis">{value || "（空）"}</span>,
            },
            {
              title: "AI 建议",
              dataIndex: "suggested_value",
              width: 200,
              render: (value: string | null) => <strong className="cell-ellipsis">{value || "（无建议）"}</strong>,
            },
            {
              title: "置信度",
              dataIndex: "confidence",
              width: 76,
              render: (value: string | null) => (
                <Tag color={value === "high" ? "green" : value === "medium" ? "gold" : "default"}>
                  {CONFIDENCE_LABELS[value ?? ""] ?? "低"}
                </Tag>
              ),
            },
            {
              title: "AI 理由 / 证据",
              render: (_, row) => (
                <div>
                  <div>{row.reason || "（无理由）"}</div>
                  {row.evidence && (
                    <a href={row.evidence} target="_blank" rel="noreferrer" className="muted">
                      查看来源
                    </a>
                  )}
                </div>
              ),
            },
            {
              title: "人工判定",
              width: 150,
              render: (_, row) =>
                row.verdict ? (
                  <Tooltip title={(row.labeled_by ?? "") + " · " + (row.labeled_at ?? "")}>
                    <Tag color={row.verdict === "agree" ? "green" : "red"}>
                      {row.verdict === "agree" ? "AI 正确" : "AI 有误"}
                    </Tag>
                  </Tooltip>
                ) : (
                  <Space size={4}>
                    <Button size="small" disabled={!canReview} onClick={() => void label(row, "agree")}>
                      对
                    </Button>
                    <Button size="small" danger disabled={!canReview} onClick={() => void label(row, "disagree")}>
                      错
                    </Button>
                  </Space>
                ),
            },
          ]}
        />
      )}

      <Collapse
        ghost
        items={[
          {
            key: "why",
            label: "这套试验怎么用、结论怎么算",
            children: (
              <ul className="muted" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.9 }}>
                <li>AI 只写建议值，不改任何核验状态；字段状态仍需你到右侧字段表点 ✓ 或 ✗ 才会变。</li>
                <li>你标「对/错」只用于统计误报率，不会自动应用到数据上。</li>
                <li>误报率 = 判为错的条数 ÷ 已标注条数；没标注的不算进分母。</li>
                <li>批次按生成时间记录，可回溯每批用了哪个模型与提示版本。</li>
              </ul>
            ),
          },
        ]}
      />
    </section>
  );
}
