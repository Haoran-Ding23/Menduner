import { useCallback, useEffect, useState } from "react";
import { Alert, Space, Table, Tag, Tooltip } from "antd";
import { Button } from "antd";
import { loadCrawlHealth, type CrawlSourceHealth } from "../../services/api";

/**
 * Which sources are working, and which have silently stopped.
 *
 * The crawl used to report "Failed" and record nothing, so a source broken for three weeks
 * looked exactly like one that blipped once. This shows the per-source last run, its status and
 * the failure reason, and raises a banner when a source has failed enough runs in a row to be
 * considered broken rather than flaky.
 */
export default function CrawlHealth() {
  const [rows, setRows] = useState<CrawlSourceHealth[]>([]);
  const [alerts, setAlerts] = useState<
    { source_id: string; source_name: string | null; consecutive_failures: number; reason: string | null }[]
  >([]);
  const [error, setError] = useState("");
  const [showAll, setShowAll] = useState(false);

  const load = useCallback(async () => {
    try {
      const health = await loadCrawlHealth();
      setRows(health.sources);
      setAlerts(health.alerts);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "读取采集状态失败");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // No local database has run a logged crawl yet; say so rather than showing an empty table.
  if (error) return <Alert type="warning" showIcon message={error} />;
  if (!rows.length) {
    return (
      <Alert
        type="info"
        showIcon
        message="尚无采集记录。运行一次采集后，这里会显示每个来源的最近状态与连续失败次数。"
      />
    );
  }

  const failing = rows.filter((r) => r.last_status === "FAILED");
  const shown = showAll ? rows : rows.filter((r) => r.last_status !== "SUCCESS");

  return (
    <>
      <div className="panel-heading">
        <Space wrap>
          <strong>采集来源状态</strong>
          <Tag color={failing.length ? "orange" : "green"}>
            本次异常 {failing.length} / {rows.length}
          </Tag>
          <small className="muted">
            每次采集都会记录：来源、开始与结束时间、状态、发现活动数、失败原因。
          </small>
        </Space>
        <Button size="small" onClick={() => setShowAll((v) => !v)}>
          {showAll ? "只看异常来源" : `显示全部 ${rows.length} 个来源`}
        </Button>
      </div>

      <Table<CrawlSourceHealth>
        rowKey="source_id"
        dataSource={shown}
        size="small"
        pagination={shown.length > 8 ? { pageSize: 8 } : false}
        scroll={{ x: 900 }}
        columns={[
          {
            title: "来源",
            render: (_, r) => (
              <>
                <strong>{r.source_name ?? r.source_id}</strong>
                <small className="block muted">{r.source_id}</small>
              </>
            ),
          },
          {
            title: "最近状态",
            width: 120,
            render: (_, r) => (
              <Tag
                color={
                  r.last_status === "SUCCESS"
                    ? "green"
                    : r.last_status === "PARTIAL"
                      ? "gold"
                      : "red"
                }
              >
                {r.last_status ?? "未知"}
              </Tag>
            ),
          },
          {
            title: "连续失败",
            width: 96,
            render: (_, r) =>
              r.consecutive_failures ? (
                <Tooltip title="每个来源连续失败 3 次会记一条告警">
                  <Tag color="red">{r.consecutive_failures} 次</Tag>
                </Tooltip>
              ) : (
                "—"
              ),
          },
          {
            title: "发现活动",
            width: 96,
            render: (_, r) => r.last_events_found ?? "—",
          },
          {
            title: "最近运行",
            width: 170,
            render: (_, r) =>
              r.last_run ? new Date(r.last_run).toLocaleString("zh-CN") : "—",
          },
          {
            title: "失败原因",
            render: (_, r) =>
              r.last_failure_reason ? (
                <small>{r.last_failure_reason}</small>
              ) : (
                "—"
              ),
          },
        ]}
      />
    </>
  );
}
