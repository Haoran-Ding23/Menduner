import { useState } from "react";
import { Alert, Button, Input, Space, Tag } from "antd";
import { usePlatform } from "../../hooks/usePlatform";
import {
  queryPrototype,
  type PrototypeQueryResult,
} from "../../services/intelligence";
export default function QueryPrototype() {
  const { dataset, filters, openEvent, go } = usePlatform();
  const [query, setQuery] = useState(
    "Which events may affect Jinji Lake hotels in October?",
  );
  const [result, setResult] = useState<{
    answer: PrototypeQueryResult;
    dataset: typeof dataset;
    context: string;
  } | null>(null);
  const context = `${filters.year}:${filters.month}:${filters.includeDemo}`;
  const current =
    result?.dataset === dataset && result.context === context
      ? result.answer
      : null;
  const run = () =>
    setResult({
      answer: queryPrototype(query, dataset, filters),
      dataset,
      context,
    });
  return (
    <section className="panel gap-top">
      <div className="panel-heading">
        <h3>AI Query Prototype · 业务查询</h3>
        <Tag color="blue">DEMO · 确定性规则，无 LLM</Tag>
      </div>
      <div className="query-content">
        <Space.Compact block>
          <Input
            aria-label="业务查询问题"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setResult(null);
            }}
            onPressEnter={run}
          />
          <Button type="primary" onClick={run}>
            查询 DEMO
          </Button>
        </Space.Compact>
        <p className="muted gap-top">
          支持中英文商圈、月份及年份；省略时间时采用当前上下文。不支持任意推理。结果由当前记录、HIGH
          规则和邻近配置酒店交集计算。
        </p>
        {current && (
          <>
            <Alert
              type={current.supported ? "info" : "warning"}
              showIcon
              message={current.message}
            />
            {current.events.map((e) => (
              <div className="upcoming-row" key={e.id}>
                <Space wrap>
                  <Button onClick={() => openEvent(e.id)}>
                    {e.name}
                    {e.demo ? " · DEMO" : ""}
                  </Button>
                  <Button size="small" onClick={() => go("/graph", e.id)}>
                    查看决策路径
                  </Button>
                  <Button size="small" onClick={() => go("/evidence", e.id)}>
                    检查证据
                  </Button>
                </Space>
              </div>
            ))}
          </>
        )}
      </div>
    </section>
  );
}
