import { Routes, Route, Navigate } from 'react-router-dom';
import { Suspense } from 'react';
import { Spin } from 'antd';
import PlatformLayout from './components/Layout';
import EventDetail from './components/EventDetail';
import ErrorBoundary from './components/ErrorBoundary';
import { lazyWithReload } from './utils/lazyWithReload';
// lazyWithReload, not lazy: a tab left open across a deploy holds an index.html naming the
// previous chunk hashes, and importing a missing chunk killed the page. It reloads once to
// pick up the new build instead of showing an error the user cannot act on.
const Map = lazyWithReload(() => import('./pages/CityEventMap'));
const Calendar = lazyWithReload(() => import('./pages/EventCalendar'));
const Graph = lazyWithReload(() => import('./pages/KnowledgeGraph'));
const Hotels = lazyWithReload(() => import('./pages/HotelIntelligence'));
const Insights = lazyWithReload(() => import('./pages/DistrictInsights'));
const Evidence = lazyWithReload(() => import('./pages/EvidenceQuality'));

/**
 * Each page gets its own boundary.
 *
 * Without one, an exception in any lazily-loaded page unmounted the entire tree and left a
 * blank white screen — which is how "知识图谱打不开" was reported, with no way to see why. Per-page
 * boundaries also keep the navigation usable, so a broken page cannot strand the user: they can
 * switch to another page instead of reloading and guessing.
 */
function Page({ name, children }: { name: string; children: React.ReactNode }) {
  return <ErrorBoundary where={name}>{children}</ErrorBoundary>;
}

export default function App() {
  return (
    <PlatformLayout>
      <Suspense fallback={<div className="loading-page"><Spin size="large"/></div>}>
        <Routes>
          <Route path="/map" element={<Page name="城市活动地图"><Map /></Page>}/>
          <Route path="/calendar" element={<Page name="活动日历"><Calendar /></Page>}/>
          <Route path="/graph" element={<Page name="知识图谱"><Graph /></Page>}/>
          <Route path="/hotels" element={<Page name="酒店活动情报"><Hotels /></Page>}/>
          <Route path="/insights" element={<Page name="商圈洞察"><Insights /></Page>}/>
          <Route path="/evidence" element={<Page name="证据与数据质量"><Evidence /></Page>}/>
          <Route path="*" element={<Navigate to="/map" replace/>}/>
        </Routes>
      </Suspense>
      {/* The event drawer renders outside the routes, so it needs its own boundary too. */}
      <ErrorBoundary where="活动详情">
        <EventDetail />
      </ErrorBoundary>
    </PlatformLayout>
  );
}
