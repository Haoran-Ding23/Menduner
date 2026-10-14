import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Empty,
  Input,
  InputNumber,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import {
  loadCoordinateTargets,
  loadVenueDuplicates,
  mergeVenues,
  setVenueCoordinates,
  type CoordinateTarget,
  type VenueDuplicate,
} from "../../services/api";

/**
 * Venue maintenance: duplicate resolution and coordinate entry.
 *
 * Both are human decisions about a VENUE ROW, not field claims about an event, so they live
 * here rather than in the per-field review table. The tool only ever PROPOSES duplicates —
 * two venues inside one building are not one venue — so the reviewer chooses the direction
 * of a merge and gives a reason, and nothing merges without that.
 */
const SIGNAL_LABEL: Record<VenueDuplicate["signal"], string> = {
  exact: "名称完全相同",
  containment: "一方名称包含另一方",
  proximity: "坐标相距很近",
};

export default function VenueMaintenance({
  reviewer,
  onChanged,
}: {
  reviewer: string;
  onChanged: () => Promise<void> | void;
}) {
  const [duplicates, setDuplicates] = useState<VenueDuplicate[]>([]);
  const [targets, setTargets] = useState<CoordinateTarget[]>([]);
  const [reason, setReason] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState("");
  const [reload, setReload] = useState(0);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [d, t] = await Promise.all([loadVenueDuplicates(), loadCoordinateTargets()]);
      setDuplicates(d);
      setTargets(t.filter((x) => !x.has_coordinates).slice(0, 40));
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "读取场馆维护数据失败");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, reload]);

  const requireReviewer = () => {
    if (!reviewer.trim()) {
      message.warning("请在上方填写审核人");
      return false;
    }
    return true;
  };

  const merge = async (row: VenueDuplicate, direction: "alias" | "canonical") => {
    if (!requireReviewer()) return;
    const key = `${row.alias_id}:${row.canonical_id}`;
    const text = (reason[key] ?? "").trim();
    if (!text) {
      message.warning("请先填写合并依据（例如：地址与官方页面一致）");
      return;
    }
    // The reviewer picks which row survives; the detector's guess is only a default.
    // "合并到 B" keeps B, so B is canonical and A is the alias that disappears.
    const aliasId = direction === "canonical" ? row.alias_id : row.canonical_id;
    const canonicalId = direction === "canonical" ? row.canonical_id : row.alias_id;
    setBusy(key);
    try {
      const result = await mergeVenues({
        aliasId,
        canonicalId,
        reviewer: reviewer.trim(),
        reason: text,
      });
      await onChanged();
      setReload((n) => n + 1);
      message.success(`已合并，迁移 ${result.events_moved} 个活动`);
    } catch (e) {
      message.error(e instanceof Error ? e.message : "合并失败");
    } finally {
      setBusy("");
    }
  };

  const saveCoordinates = async (target: CoordinateTarget, coordinates: string) => {
    if (!requireReviewer()) return;
    if (!coordinates.trim()) {
      message.warning("请从高德复制坐标，格式如 120.704315,31.322250");
      return;
    }
    setBusy(`c:${target.id}`);
    try {
      await setVenueCoordinates({
        venueId: target.id,
        coordinates: coordinates.trim(),
        reviewer: reviewer.trim(),
      });
      await onChanged();
      setReload((n) => n + 1);
      message.success(`已记录 ${target.name} 的坐标`);
    } catch (e) {
      message.error(e instanceof Error ? e.message : "保存坐标失败");
    } finally {
      setBusy("");
    }
  };

  return (
    <section className="panel gap-bottom" aria-label="场馆维护">
      <div className="panel-heading">
        <Space wrap>
          <strong>场馆维护</strong>
          <Tag color="blue">重复候选 {duplicates.length}</Tag>
          <Tag color="orange">待补坐标 {targets.length}</Tag>
          <small className="muted">
            只提出候选，不自动合并。同一栋楼里的不同场馆不是同一个场馆，方向由你决定。
          </small>
        </Space>
      </div>
      {error && <Alert type="warning" showIcon message={error} />}

      <Typography.Title level={5} style={{ marginTop: 12 }}>
        重复场馆候选
      </Typography.Title>
      {duplicates.length ? (
        <Table<VenueDuplicate>
          rowKey={(r) => `${r.alias_id}:${r.canonical_id}`}
          dataSource={duplicates}
          size="small"
          pagination={{ pageSize: 5 }}
          scroll={{ x: 900 }}
          columns={[
            {
              title: "候选 A",
              render: (_, r) => (
                <>
                  <strong>{r.alias_name}</strong>
                  <small className="block muted">{r.alias_events} 个活动</small>
                </>
              ),
            },
            {
              title: "候选 B",
              render: (_, r) => (
                <>
                  <strong>{r.canonical_name}</strong>
                  <small className="block muted">
                    {r.canonical_events} 个活动
                    {r.canonical_has_coordinates ? " · 有坐标" : ""}
                  </small>
                </>
              ),
            },
            {
              title: "信号",
              width: 170,
              render: (_, r) => (
                <>
                  <Tag color={r.signal === "exact" ? "green" : r.signal === "containment" ? "blue" : "orange"}>
                    {SIGNAL_LABEL[r.signal]}
                  </Tag>
                  {r.distance_km !== null && (
                    <small className="block muted">相距 {r.distance_km} km</small>
                  )}
                  {r.alias_looks_like_address && (
                    <small className="block muted">一侧名称其实是整行地址</small>
                  )}
                  {r.notes.map((n) => (
                    <small className="block muted" key={n}>
                      {n}
                    </small>
                  ))}
                </>
              ),
            },
            {
              title: "合并依据 / 操作",
              width: 320,
              render: (_, r) => {
                const key = `${r.alias_id}:${r.canonical_id}`;
                return (
                  <Space direction="vertical" size={4} style={{ width: "100%" }}>
                    <Input
                      size="small"
                      aria-label={`合并依据 ${r.alias_name}`}
                      placeholder="依据，例如：官方页面地址一致"
                      value={reason[key] ?? ""}
                      onChange={(e) =>
                        setReason((prev) => ({ ...prev, [key]: e.target.value }))
                      }
                    />
                    <Space size={4} wrap>
                      <Button
                        size="small"
                        type="primary"
                        ghost
                        loading={busy === key}
                        onClick={() => void merge(r, "canonical")}
                      >
                        合并到「{r.canonical_name.slice(0, 8)}」
                      </Button>
                      <Button
                        size="small"
                        loading={busy === key}
                        onClick={() => void merge(r, "alias")}
                      >
                        反向合并
                      </Button>
                    </Space>
                  </Space>
                );
              },
            },
          ]}
        />
      ) : (
        <Empty description="没有待决的重复候选" />
      )}

      <Typography.Title level={5} style={{ marginTop: 16 }}>
        待补坐标场馆（被活动引用但尚无坐标）
      </Typography.Title>
      {targets.length ? (
        <Table<CoordinateTarget>
          rowKey="id"
          dataSource={targets}
          size="small"
          pagination={{ pageSize: 5 }}
          scroll={{ x: 900 }}
          columns={[
            {
              title: "场馆",
              render: (_, t) => (
                <>
                  <strong>{t.name}</strong>
                  <small className="block muted">
                    {t.events} 个活动 · {t.address ?? "地址待核验"}
                  </small>
                </>
              ),
            },
            {
              title: "经度 / 纬度 / 来源 URL",
              render: (_, t) => <CoordinateRow target={t} busy={busy} onSave={saveCoordinates} />,
            },
          ]}
        />
      ) : (
        <Empty description="所有被引用的场馆都已有坐标" />
      )}
    </section>
  );
}

function CoordinateRow({
  target,
  busy,
  onSave,
}: {
  target: CoordinateTarget;
  busy: string;
  onSave: (target: CoordinateTarget, coordinates: string) => Promise<void>;
}) {
  const [coordinates, setCoordinates] = useState("");
  const [saving, setSaving] = useState(false);
  return (
    <Space wrap size={4} align="start">
      {/* One field, because AMap's 坐标拾取 copies the pair as a single string. No source-URL
          field: AMap's web UI has no stable per-place URL to copy, so demanding one blocked
          every entry — the API resolves the AMap place from the coordinate instead. */}
      <Input
        size="small"
        aria-label={`坐标 ${target.name}`}
        placeholder="从高德复制：120.704315,31.322250"
        value={coordinates}
        onChange={(e) => setCoordinates(e.target.value)}
        style={{ width: 260 }}
      />
      <Button
        size="small"
        loading={saving || busy === `c:${target.id}`}
        onClick={() => {
          setSaving(true);
          void onSave(target, coordinates).finally(() => setSaving(false));
        }}
      >
        保存坐标
      </Button>
      <a
        href={`https://www.amap.com/search?query=${encodeURIComponent(target.name)}`}
        target="_blank"
        rel="noreferrer"
      >
        在高德查找 ↗
      </a>
    </Space>
  );
}
