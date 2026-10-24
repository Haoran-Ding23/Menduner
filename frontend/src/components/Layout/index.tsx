import { useEffect, useMemo, useState, useRef } from "react";
import { useLocation } from "react-router-dom";
import { Button, Tag, Modal, Alert, Space, message, Descriptions, Drawer } from "antd";
import {
  EnvironmentOutlined,
  DashboardOutlined,
  CalendarOutlined,
  ApartmentOutlined,
  HomeOutlined,
  BankOutlined,
  BarChartOutlined,
  SafetyCertificateOutlined,
  CrownOutlined,

  ToolOutlined,
  SettingOutlined,
  UploadOutlined,
  ReloadOutlined,
  UnorderedListOutlined,
  ShopOutlined,
  DatabaseOutlined,
  AppstoreOutlined,
} from "@ant-design/icons";
import { usePlatform } from "../../hooks/usePlatform";
import { canReview, useIdentity } from "../../hooks/useIdentity";
import { useAccount, useEntitlements } from "../../hooks/useEntitlements";

import { FILING_MODE, SITE_SHORT, SITE_TAGLINE, SITE_TITLE } from "../../config";
export interface NavPage {
  /** Part of the commercial edition. No longer gated by a plan, but hidden during the ICP
   *  filing review, which requires a non-commercial information site. */
  path: string;
  title: string;
  label: string;
  icon: React.ReactNode;
  commercial?: boolean;
  /** 侧栏分组：回答同一个问题的页面放在一起，避免 9 个平级条目。 */
  group?: string;
}
export const pages: NavPage[] = [
  {
    path: "/workbench",
    title: "本店工作台",
    label: "本店工作台",
    icon: <DashboardOutlined />,
      group: "每天要用",
},
  {
    path: "/map",
    title: "城市活动地图",
    label: "城市活动地图",
    icon: <EnvironmentOutlined />,
      group: "活动浏览",
},
  // 活动日历 / 场馆活动清单 used to sit here as separate entries. All three views answered the
  // same question from different angles, and the list already groups by 本周/本月, so the
  // navigation offers one entry: 活动清单.
  {
    path: "/agenda",
    title: "活动清单",
    label: "活动清单",
    icon: <UnorderedListOutlined />,
      group: "活动浏览",
},
  {
    path: "/private",
    title: "本店经营数据",
    label: "本店经营数据",
    icon: <DatabaseOutlined />,
      group: "数据与来源",
},
  {
    path: "/graph",
    title: "知识图谱",
    label: "知识图谱",
    icon: <ApartmentOutlined />,
      group: "酒店与商圈",
},
  {
    path: "/find-hotels",
    title: "找酒店",
    label: "找酒店",
    icon: <BankOutlined />,
    commercial: true,
      group: "酒店与商圈",
},
  {
    path: "/hotels",
    title: "酒店活动情报",
    label: "酒店活动情报",
    icon: <HomeOutlined />,
    commercial: true,
      group: "酒店与商圈",
},
  {
    path: "/insights",
    title: "商圈洞察",
    label: "商圈洞察",
    icon: <BarChartOutlined />,
    commercial: true,
      group: "酒店与商圈",
},
  {
    path: "/evidence",
    title: "数据质量与来源",
    label: "数据质量与来源",
    icon: <SafetyCertificateOutlined />,
      group: "数据与来源",
},
];

// The customer's upgrade entry. Visible to everyone: a customer must be able to see what a paid
// plan would unlock before deciding anything.
export const plansPage: NavPage = {
  path: "/plans",
  title: "套餐与升级",
  label: "套餐与升级",
  icon: <CrownOutlined />,
};

// Internal operations. Not a public page: shown only to a reviewer/admin, and its endpoints
// are server-side role-checked regardless of what the navigation renders.
export const consolePage: NavPage = {
  path: "/review",
  title: "审核台",
  label: "审核台",
  icon: <ToolOutlined />,
};
export default function PlatformLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const location = useLocation();
  const [moreOpen, setMoreOpen] = useState(false);
  const { dataset, filters, go, importData, resetData, dataMode, reloadData } =
    usePlatform();
  const { identity } = useIdentity();

  const { state: accountState } = useAccount();
  // Filing review must see a non-commercial information site: the paid workflow, the plan page and
  // the account entry disappear (their routes also redirect, see App.tsx). Nothing is deleted.
  // No paywall on the navigation: the commercial edition is paused, so every workspace page is
  // open to whoever is signed in. The plan fields in the database and the account plan badge are
  // untouched, so reintroducing a paid tier later is a change here rather than a migration.
  const visiblePages = FILING_MODE ? pages.filter((item) => !item.commercial) : pages;
  const navPages: NavPage[] = [
    ...visiblePages,
    ...(canReview(identity) ? [consolePage] : []),
  ];
  const page = navPages.find((p) => p.path === location.pathname);
  const navGroups = useMemo(() => {
    const order = ["每天要用", "活动浏览", "酒店与商圈", "数据与来源"];
    return order
      .map((name) => ({ name, pages: navPages.filter((p) => (p.group ?? "活动浏览") === name) }))
      .filter((group) => group.pages.length > 0);
  }, [navPages]);
// Auth and plan pages are reachable but are not workspace entries, so the breadcrumb had no
// title for them and rendered "工作空间 / " with nothing after the slash.
const AUTH_PAGE_TITLES: Record<string, string> = {
  "/login": "登录",
  "/register": "注册",
  "/plans": "套餐与升级",
};
const pageTitle = page?.title ?? AUTH_PAGE_TITLES[location.pathname] ?? "";
  const [settings, setSettings] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const [api, holder] = message.useMessage();
  useEffect(() => {
    // Pages that name their own subject (the map, which follows month and region) override this;
    // everything else simply states where the reader is.
    document.title = pageTitle ? `${pageTitle} · ${SITE_SHORT}` : SITE_TITLE;
  }, [pageTitle]);
  return (
    <div className="platform">
      {holder}
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-symbol">M</span>
          <div>
            Menduner<small>{SITE_TAGLINE}</small>
          </div>
        </div>
        <nav>
          {navGroups.map((group) => (
            <div key={group.name} className="nav-group">
              <div className="nav-section">{group.name}</div>
              {group.pages.map((p) => (
            <button
              key={p.path}
              className={
                "nav-item " + (p.path === location.pathname ? "active" : "")
              }
              onClick={() => go(p.path)}
            >
              {p.icon}
              <span>{p.label}</span>
            </button>
              ))}
            </div>
          ))}
          {/* 移动端底部只保留前几个主入口，其余收进「更多」：九个入口排成多行会占掉四分之一屏。 */}
          <button className="nav-item nav-more" onClick={() => setMoreOpen(true)}>
            <AppstoreOutlined />
            <span>更多</span>
          </button>
        </nav>
        <Drawer
          placement="bottom"
          height="62vh"
          open={moreOpen}
          onClose={() => setMoreOpen(false)}
          title="全部功能"
        >
          {navGroups.map((group) => (
            <div key={group.name} className="drawer-group">
              <div className="nav-section">{group.name}</div>
              {group.pages.map((page) => (
                <button
                  key={page.path}
                  className={"drawer-item " + (page.path === location.pathname ? "active" : "")}
                  onClick={() => {
                    setMoreOpen(false);
                    go(page.path);
                  }}
                >
                  {page.icon}
                  <span>{page.label}</span>
                </button>
              ))}
            </div>
          ))}
        </Drawer>
        <div className="sidebar-foot">
          <Tag color="cyan">ENT303TC · 第 14 组</Tag>
          <p>城市活动知识图谱</p>
          <small>V1.3 / 采集管线原型</small>
          <div className="gap-top">
            {FILING_MODE ? (
              <Tag>公开活动信息展示</Tag>
            ) : accountState.authenticated ? (
              <Tag color="cyan">{accountState.account?.login}</Tag>
            ) : (
              <Button size="small" onClick={() => go("/login")}>
                登录 / 注册
              </Button>
            )}
          </div>
        </div>
      </aside>
      <div className="workspace">
        <header>
          <div>
            <span className="breadcrumb">工作空间 / </span>
            <strong>{pageTitle}</strong>
          </div>
          <Space>
            <span className="header-year">{filters.year}</span>
            <Tag color="blue">
             {SITE_SHORT} · {dataset.events.length} 条
            </Tag>
            {/* The status strip was removed from the page body, but a refresh control must
                stay reachable, and a connection failure has to be visible because it
                changes what the numbers mean. */}
            {dataMode !== "api" && dataMode !== "demo" && (
              <Tag color={dataMode === "error" ? "red" : "orange"}>
                {
                  {
                    loading: "读取中",
                    error: "API 不可用",
                    stale: "API 已断开 · 上次快照",
                    import: "手动导入 · 当前会话",
                    demo: "",
                    api: "",
                  }[dataMode]
                }
              </Tag>
            )}
            <Button
              aria-label="刷新 API 数据"
              title="刷新 API 数据"
              icon={<ReloadOutlined />}
              loading={dataMode === "loading"}
              onClick={() => void reloadData()}
            />
            <Button
              aria-label="设置与数据导入"
              icon={<SettingOutlined />}
              onClick={() => setSettings(true)}
            />
          </Space>
        </header>
        <main>
          {children}
        </main>
      </div>
      <Modal
        title="设置与数据导入"
        open={settings}
        onCancel={() => setSettings(false)}
        footer={null}
      >
        <Alert
          type="info"
          showIcon
          message="六页共享同一份数据快照"
          description="导入完整数据集或活动数组。只有具有来源 URL 的已核验 GCJ-02 坐标会显示在地图上。手动导入仅保留于当前会话，不写入数据库；刷新页面重新读取 API。"
        />
        <Descriptions
          className="gap-top"
          column={1}
          items={[
            {
              key: "count",
              label: "活动记录",
              children: dataset.events.length,
            },
            { key: "date", label: "更新时间", children: dataset.updatedAt },
            {
              key: "map",
              label: "地图配置",
              children: import.meta.env.VITE_AMAP_KEY
                ? "已提供配置；连接结果见地图"
                : "尚未配置",
            },
          ]}
        />
        <Space className="gap-top">
          <Button
            icon={<UploadOutlined />}
            onClick={() => input.current?.click()}
          >
            导入 JSON
          </Button>
          <Button
            onClick={() => {
              resetData();
              api.success("已切换到本地 DEMO；未修改数据库");
            }}
          >
            使用本地 DEMO
          </Button>
        </Space>
        <input
          ref={input}
          type="file"
          accept=".json,application/json"
          hidden
          onChange={async (e) => {
            const file = e.target.files?.[0];
            if (!file) return;
            try {
              if (file.size > 10 * 1024 * 1024)
                throw new Error("文件超过 10 MB");
              importData(JSON.parse(await file.text()));
              api.success("导入成功");
              setSettings(false);
            } catch (error) {
              api.error(error instanceof Error ? error.message : "导入失败");
            } finally {
              e.target.value = "";
            }
          }}
        />
        <p className="muted">
          地图安全密钥由服务器读取。修改 .env.local 后需重启 npm run dev。
        </p>
      </Modal>
    </div>
  );
}
