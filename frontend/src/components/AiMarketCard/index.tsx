import { useEffect, useState } from "react";
import { Collapse, Tag, Tooltip } from "antd";
import { loadAiMarketAnalysis, type AiMarketAnalysis } from "../../services/api";

/**
 * AI 商圈解读（GPT Round 21 批准的「证据约束型」）。
 *
 * 三条硬规则写在界面里，而不是只写在文档里：
 *   1. 标注「AI 生成 · 未经核实」，不能让它看起来像官方结论；
 *   2. 每条结论后面列出它引用的指标键，用户可以对照上面的数字；
 *   3. 模型编造的数字与禁止措辞已经被后端丢弃，若有被丢弃项，折叠区里如实显示条数。
 */
export default function AiMarketCard({
  areaId,
  radius,
  start,
  end,
}: {
  areaId: string | null;
  radius: number;
  start: string;
  end: string;
}) {
  const [data, setData] = useState<AiMarketAnalysis | null>(null);
  const [error, setError] = useState<string>("");

  useEffect(() => {
    if (!areaId) return undefined;
    let alive = true;
    setData(null);
    setError("");
    loadAiMarketAnalysis(areaId, { radius, start, end })
      .then((next) => alive && setData(next))
      .catch((reason: Error) => alive && setError(reason.message));
    return () => {
      alive = false;
    };
  }, [areaId, radius, start, end]);

  if (error) return null;

  return (
    <section className="insight-card ai-card" aria-label="AI 商圈解读">
      <div className="card-head">
        <h3>
          AI 解读
          <Tag style={{ marginLeft: 8 }} color="default">
            AI 生成 · 未经核实
          </Tag>
        </h3>
        <span className="insight-muted">只解释上面的数字，不预测经营结果</span>
      </div>

      {!data ? (
        <p className="insight-muted">正在生成解读…</p>
      ) : !data.available ? (
        <p className="insight-muted">{data.reason ?? "AI 解读暂不可用"}</p>
      ) : (
        <>
          <p className="ai-summary">{data.summary || "（模型未给出概要）"}</p>

          {data.findings.length > 0 && (
            <ul className="ai-findings">
              {data.findings.map((finding) => (
                <li key={finding.claim}>
                  {finding.claim}
                  <span className="ai-metric-keys">
                    {finding.metricKeys.map((key) => (
                      <Tooltip key={key} title={"引用指标：" + key}>
                        <code>{key}</code>
                      </Tooltip>
                    ))}
                  </span>
                </li>
              ))}
            </ul>
          )}

          {data.unknowns.length > 0 && (
            <p className="insight-muted">
              还不知道：{data.unknowns.join("、")}
            </p>
          )}
          {data.limitations.length > 0 && (
            <p className="insight-muted">使用限制：{data.limitations.join("；")}</p>
          )}

          <Collapse
            ghost
            items={[
              {
                key: "audit",
                label:
                  "查看被丢弃的 AI 内容（" +
                  data.rejected.length +
                  " 条）与可继续问的问题",
                children: (
                  <>
                    {data.rejected.length === 0 ? (
                      <p className="insight-muted">本次没有被丢弃的结论</p>
                    ) : (
                      <ul className="ai-rejected">
                        {data.rejected.map((item) => (
                          <li key={item.claim + item.reason}>
                            {item.claim || "（空结论）"} —— {item.reason}
                          </li>
                        ))}
                      </ul>
                    )}
                    {data.businessQuestions.length > 0 && (
                      <p className="insight-muted">
                        可以继续问：{data.businessQuestions.join("；")}
                      </p>
                    )}
                  </>
                ),
              },
            ]}
          />
        </>
      )}
    </section>
  );
}
