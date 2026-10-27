import { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, Button, Empty, Select, Space, Tag, Tooltip, message } from "antd";
import { usePlatform } from "../../hooks/usePlatform";
import { useAccount } from "../../hooks/useEntitlements";
import { rankEvents } from "../../services/ranking";
import { categories } from "../../utils/data";
import { beijingToday, shiftDate, type TimeWindow } from "../../utils/caliber";
import { canonicalIdOf, distinctByCanonical } from "../../utils/dedupe";
import CaliberBar from "../../components/CaliberBar";
import type { Event, Hotel } from "../../types";

/**
 * 本店工作台：一天开始时要看的一页。
 *
 * 四块内容分别回答四个问题：接下来七天有哪些值得关注、和上次相比什么变了、我答应了要跟进
 * 什么、接下来去地图还是出周报。
 *
 * 三个刻意的取舍：
 *   * 酒店选择存在浏览器里，不存服务器 —— 它只是「我关心哪一家」，属于个人偏好，不是账号数据；
 *   * 「本周变化」在没有两份快照时显示「尚无可比较记录」，而不是「没有变化」——后者会让人以为
 *     数据是稳的，前者才说明系统还没积累出比较能力；
 *   * 跟进状态必须登录且按酒店隔离，未登录时按钮提示登录而不是假装保存成功。
 */

const HOTEL_KEY = "menduner.workbench.hotel";

const FOLLOW_STATES = [
  { value: "watching", label: "关注" },
  { value: "todo", label: "待跟进" },
  { value: "done", label: "已跟进" },
  { value: "ignored", label: "忽略" },
] as const;

const ADOPT_OPTIONS = [
  { value: "unknown", label: "采纳：未知" },
  { value: "adopted", label: "已采纳" },
  { value: "declined", label: "未采纳" },
] as const;

interface Followup {
  eventKey: string;
  state: string;
  stateLabel: string;
  note: string | null;
  updatedAt: string;
  adopted?: string;
  adoptedLabel?: string;
  feedback?: string | null;
}

interface Changes {
  comparable: boolean;
  reason?: string;
  from?: string;
  to?: string;
  added: { event_key: string; name: string; start_date: string | null }[];
  cancelled: { event_key: string; name: string; start_date: string | null }[];
  rescheduled: { before: { name: string; start_date: string | null }; after: { name: string; start_date: string | null } }[];
  changed: { before: { name: string }; after: { name: string } }[];
}

/** 维度分数展示：缺失维度显示「未知」，不补 0，避免看起来像算过了但很低。 */
function fmtDim(value: number | null): string {
  return value === null ? "未知" : value.toFixed(2);
}

export default function Workbench() {
  const { dataset, filters, update } = usePlatform();
  const { state: accountState } = useAccount();
  const [hotelId, setHotelId] = useState<string>(() => {
    try {
      return window.localStorage.getItem(HOTEL_KEY) ?? "";
    } catch {
      return "";
    }
  });
  const [changes, setChanges] = useState<Changes | null>(null);
    // 跟进列表必须显示活动名，不能给客户看 evt-xxx 这种内部 ID
  const eventNameOf = (key: string) =>
    dataset.events.find((event) => event.id === key || event.canonicalId === key)?.name ?? '活动名称待补充';
const [followups, setFollowups] = useState<Followup[]>([]);
  const [followupError, setFollowupError] = useState("");
  const [busy, setBusy] = useState("");

  const hotels = dataset.hotels;
  const hotel: Hotel | undefined = hotels.find((h) => h.id === hotelId) ?? hotels[0];

  // Remember the choice. localStorage is unavailable in private mode, and this is a preference,
  // so failing to store it must not break the page.
  useEffect(() => {
    if (!hotel) return;
    if (hotel.id !== hotelId) setHotelId(hotel.id);
    try {
      window.localStorage.setItem(HOTEL_KEY, hotel.id);
    } catch {
      /* preference only */
    }
  }, [hotel, hotelId]);

  const today = beijingToday();
  const weekWindow: TimeWindow = useMemo(
    () => ({
      kind: "next7",
      start: today,
      end: shiftDate(today, 6),
      label: `未来 7 天（${today} 至 ${shiftDate(today, 6)}）`,
    }),
    [today],
  );

  // 未来七天、且与这家酒店有距离关系的活动；按关注等级→距离排序，理由写在卡片上。
  // 排序交给 services/ranking：规则与权重集中配置，这里只负责取窗口内的活动。
  const worthWatching = useMemo(() => {
    if (!hotel) return [];
    const inWindow = distinctByCanonical(
      dataset.events.filter((event) => {
        const start = event.startDate;
        if (!start) return false;
        const end = event.endDate ?? start;
        return start <= weekWindow.end && end >= weekWindow.start;
      }),
    );
    return rankEvents(inWindow, { hotel, dataset, today }).slice(0, 8);
  }, [dataset, hotel, weekWindow, today]);

  const loadChanges = useCallback(async () => {
    try {
      const response = await fetch("/api/workbench/changes", { cache: "no-store" });
      if (!response.ok) return;
      setChanges((await response.json()) as Changes);
    } catch {
      /* 变化是加分项，取不到时页面其余部分照常 */
    }
  }, []);

  const loadFollowups = useCallback(async () => {
    if (!accountState.authenticated) {
      setFollowups([]);
      return;
    }
    try {
      const response = await fetch("/api/workbench/followups", { cache: "no-store" });
      if (response.status === 401 || response.status === 403) {
        setFollowupError("登录后才能保存跟进状态");
        return;
      }
      const body = await response.json();
      setFollowups((body.items ?? []) as Followup[]);
      setFollowupError("");
    } catch {
      setFollowupError("跟进状态读取失败");
    }
  }, [accountState.authenticated]);

  useEffect(() => {
    void loadChanges();
    void loadFollowups();
  }, [loadChanges, loadFollowups]);

  // 采纳状态单独提交：改状态时不要把已有采纳结论清空。
  const setAdoption = async (eventKey: string, adopted: string) => {
    setBusy(eventKey + ":adopt");
    try {
      const response = await fetch("/api/workbench/followups", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ eventKey, state: stateOf(eventKey) ?? "todo", adopted }),
      });
      if (response.status === 401 || response.status === 403) {
        message.warning("请先登录后再保存");
        return;
      }
      if (!response.ok) throw new Error("保存失败");
      await loadFollowups();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "保存失败");
    } finally {
      setBusy("");
    }
  };

  const setFollowup = async (eventKey: string, state: string) => {
    setBusy(`${eventKey}:${state}`);
    try {
      const response = await fetch("/api/workbench/followups", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ eventKey, state }),
      });
      if (response.status === 401 || response.status === 403) {
        message.warning("请先登录后再保存跟进状态");
        return;
      }
      if (!response.ok) throw new Error("保存失败");
      message.success(`已标记为${FOLLOW_STATES.find((s) => s.value === state)?.label}`);
      await loadFollowups();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "保存失败");
    } finally {
      setBusy("");
    }
  };

  const stateOf = (eventKey: string) =>
    followups.find((row) => row.eventKey === eventKey)?.state;

  const openOnMap = (event: Event) => {
    const params = new URLSearchParams();
    if (event.districtId) params.set("district", event.districtId);
    // 关键：必须带上活动 id，否则地图无法定位这条活动（用户已指出这个断链）
    params.set("event", event.id);
    if (event.startDate) {
      params.set("year", event.startDate.slice(0, 4));
      params.set("month", String(Number(event.startDate.slice(5, 7))));
    }
    update({
      district: event.districtId ?? null,
      year: Number((event.startDate ?? today).slice(0, 4)),
      month: Number((event.startDate ?? today).slice(5, 7)),
    });
    window.location.assign(`/map?${params.toString()}`);
  };

  if (!hotel) {
    return (
      <Alert
        type="warning"
        showIcon
        message="还没有可选的酒店"
        description="酒店库为空，无法生成工作台。请先在「找酒店」中确认酒店数据已导入。"
      />
    );
  }

  return (
    <>
      <div className="page-heading">
        <h1>本店工作台</h1>
      </div>

      <div className="workbench-head">
        <Space wrap size={12}>
          <span className="muted">当前酒店</span>
          <Select
            style={{ minWidth: 260 }}
            aria-label="选择酒店"
            value={hotel.id}
            onChange={(value) => setHotelId(value)}
            options={hotels.map((item) => ({
              value: item.id,
              label: item.tierLabel ? `${item.name}（${item.tierLabel}）` : item.name,
            }))}
          />
          <Button onClick={() => window.location.assign("/find-hotels")}>换一家酒店</Button>
          <Button type="primary" onClick={() => openOnMap(worthWatching[0]?.event ?? { ...({} as Event) })}>
            在地图上看
          </Button>
          <Tooltip title="导出包含重点活动、推荐理由、本周变化与待办的周报">
            <Space size={4}>
              <Button href="/api/private/weekly.xlsx" download>
                周报 Excel
              </Button>
              <Button href="/api/private/weekly.pdf" download>
                周报 PDF
              </Button>
            </Space>
          </Tooltip>
        </Space>
        <small className="muted">
          地址：{hotel.address ?? "未记录"} · 坐标：{hotel.coordinates ? "已核验" : "未核验（距离无法计算）"}
        </small>
      </div>

      <CaliberBar window={weekWindow} events={dataset.events.filter((e) => {
        const start = e.startDate;
        if (!start) return false;
        const end = e.endDate ?? start;
        return start <= weekWindow.end && end >= weekWindow.start;
      })} />

      {/* F09：把四个范围分开写，避免一个数字被当成三种含义（审核实测工作台 147 与酒店页 241
          被读成矛盾，其实一个是全市窗口样本、一个是半径内匹配集）。 */}
      <p className="workbench-scope">
        样本：全市 {dataset.events.length} 个活动身份（已按来源去重）；窗口：未来 7 天{" "}
        {weekWindow.start} 至 {weekWindow.end}（北京时间）；本店半径：15 km，距离按已核验坐标计算；
        推荐集：以上条件下按规则排序取前 {worthWatching.length} 条
      </p>

      <section className="panel gap-bottom">
        <div className="panel-heading">
          <h3 style={{ margin: 0 }}>未来七天值得关注</h3>
          <small className="muted">按业务相关性、距离、数据可信度与紧迫度排序；缺数据的维度标为未知，不作推测</small>
        </div>
        {worthWatching.length === 0 ? (
          <Empty description="未来七天没有与这家酒店相关的活动" />
        ) : (
          <div className="workbench-list">
            {worthWatching.map(({ event, reasons, unknown, byDimension }) => (
              <article className="workbench-row" key={canonicalIdOf(event)}>
                <div className="workbench-main">
                  <div className="workbench-title">
                    <button className="link-button" onClick={() => openOnMap(event)}>
                      {event.name}
                    </button>
                    <Tag color={categories[event.category]?.color}>{categories[event.category]?.label}</Tag>
                  </div>
                  <small className="muted">
                    {event.startDate ?? "日期待核验"} → {event.endDate ?? "结束待核验"}
                  </small>
                  {/* 推荐理由与维度分数分开显示：距离近不等于值得投入，用户要能看到两件事。 */}
                  <small className="rank-reasons">{reasons.join(" · ")}</small>
                  {(() => {
                    // 主界面只说人话；分档规则与原始分数放 tooltip，避免变成黑箱打分
                    const level = (value: number | null, high: number, mid: number) =>
                      value === null ? "不足" : value >= high ? "高" : value >= mid ? "中" : "低";
                    const worth = level(
                      byDimension.relevance === null || byDimension.timing === null
                        ? null
                        : (byDimension.relevance + byDimension.timing) / 2,
                      0.75,
                      0.5,
                    );
                    const reliable = level(byDimension.credibility, 0.75, 0.4);
                    return (
                      <small className="rank-plain">
                        值得关注：<strong>{worth}</strong> · 信息可靠：<strong>{reliable}</strong>
                        <Tooltip
                          title={
                            "值得关注 = 业务相关性与紧迫度的平均（≥0.75 高，≥0.5 中，其余低）；" +
                            "信息可靠 = 关键字段的证据覆盖率（≥0.75 高，≥0.4 中，其余低）。原始分数：" +
                            "相关性 " + fmtDim(byDimension.relevance) +
                            " · 距离 " + fmtDim(byDimension.distance) +
                            " · 可信度 " + fmtDim(byDimension.credibility) +
                            " · 紧迫度 " + fmtDim(byDimension.timing)
                          }
                        >
                          <span className="rank-help">怎么判断的</span>
                        </Tooltip>
                      </small>
                    );
                  })()}
                  {unknown.length > 0 && (
                    <small className="rank-unknown">还没确认：{unknown.join("；")}</small>
                  )}
                </div>
                <Space size={4} wrap>
                  {FOLLOW_STATES.map((option) => (
                    <Button
                      key={option.value}
                      size="small"
                      type={stateOf(canonicalIdOf(event)) === option.value ? "primary" : "default"}
                      loading={busy === `${canonicalIdOf(event)}:${option.value}`}
                      onClick={() => void setFollowup(canonicalIdOf(event), option.value)}
                    >
                      {option.label}
                    </Button>
                  ))}
                </Space>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="panel gap-bottom">
        <div className="panel-heading">
          <h3 style={{ margin: 0 }}>本周变化</h3>
          {changes?.comparable && (
            <small className="muted">
              比较 {changes.from} 与 {changes.to}
            </small>
          )}
        </div>
        {!changes || !changes.comparable ? (
          <Empty
            description={
              changes?.reason ??
              "尚无可比较记录 —— 快照每天记录一次，积累两份之后这里会显示新增、取消与改期"
            }
          />
        ) : (
          <Space direction="vertical" style={{ width: "100%" }} size={6}>
            {changes.added.length > 0 && (
              <div>
                <Tag color="green">新增 {changes.added.length}</Tag>
                <small className="muted">
                  {changes.added.slice(0, 6).map((item) => item.name).join("、")}
                </small>
              </div>
            )}
            {changes.rescheduled.length > 0 && (
              <div>
                <Tag color="gold">改期 {changes.rescheduled.length}</Tag>
                <small className="muted">
                  {changes.rescheduled.slice(0, 6).map(
                    (item) => `${item.after.name}：${item.before.start_date ?? "?"} → ${item.after.start_date ?? "?"}`,
                  ).join("；")}
                </small>
              </div>
            )}
            {changes.cancelled.length > 0 && (
              <div>
                <Tag color="red">取消 {changes.cancelled.length}</Tag>
                <small className="muted">
                  {changes.cancelled.slice(0, 6).map((item) => item.name).join("、")}
                </small>
              </div>
            )}
            {changes.changed.length > 0 && (
              <div>
                <Tag>信息变化 {changes.changed.length}</Tag>
                <small className="muted">
                  {changes.changed.slice(0, 6).map((item) => item.after.name).join("、")}
                </small>
              </div>
            )}
            {changes.added.length + changes.rescheduled.length + changes.cancelled.length +
              changes.changed.length === 0 && <Empty description="两份快照之间没有变化" />}
          </Space>
        )}
      </section>

      <section className="panel">
        <div className="panel-heading">
          <h3 style={{ margin: 0 }}>我的跟进</h3>
          <small className="muted">状态保存在本店账号下，成员共享</small>
        </div>
        {followupError && <Alert type="info" showIcon message={followupError} />}
        {followups.length === 0 ? (
          <Empty description="还没有标记任何活动。在上面的列表里点「关注」或「待跟进」即可。" />
        ) : (
          <div className="workbench-list">
            {followups.map((row) => (
              <article className="workbench-row" key={row.eventKey}>
                <div className="workbench-main">
                  <strong>{eventNameOf(row.eventKey)}</strong>
                  <small className="muted">
                    {row.stateLabel} · 更新于 {row.updatedAt.slice(0, 16).replace("T", " ")}
                    {row.note ? ` · ${row.note}` : ""}
                  </small>
                </div>
                <Space size={4} wrap>
                  <Select
                    size="small"
                    style={{ width: 110 }}
                    value={row.adopted ?? "unknown"}
                    loading={busy === row.eventKey + ":adopt"}
                    onChange={(value) => void setAdoption(row.eventKey, value)}
                    options={ADOPT_OPTIONS.map((option) => ({ value: option.value, label: option.label }))}
                  />
                  {FOLLOW_STATES.map((option) => (
                    <Button
                      key={option.value}
                      size="small"
                      type={row.state === option.value ? "primary" : "default"}
                      loading={busy === `${row.eventKey}:${option.value}`}
                      onClick={() => void setFollowup(row.eventKey, option.value)}
                    >
                      {option.label}
                    </Button>
                  ))}
                </Space>
              </article>
            ))}
          </div>
        )}
      </section>

      {!accountState.authenticated && (
        <Alert
          className="gap-top"
          type="info"
          showIcon
          message="当前未登录"
          description="「未来七天值得关注」和「本周变化」可以直接看；保存关注/跟进状态需要登录本店账号。"
        />
      )}
    </>
  );
}
