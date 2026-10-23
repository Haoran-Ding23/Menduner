import { Routes, Route, Navigate } from 'react-router-dom';
import { Suspense } from 'react';
import { Spin } from 'antd';
import PlatformLayout from './components/Layout';
import EventDetail from './components/EventDetail';
import ErrorBoundary from './components/ErrorBoundary';
import { AccountProvider } from './hooks/useEntitlements';
import { IdentityProvider } from './hooks/useIdentity';
import type { AccountState } from './services/account';
import { FILING_MODE } from './config';
import { lazyWithReload } from './utils/lazyWithReload';
// lazyWithReload, not lazy: a tab left open across a deploy holds an index.html naming the
// previous chunk hashes, and importing a missing chunk killed the page. It reloads once to
// pick up the new build instead of showing an error the user cannot act on.
const Workbench = lazyWithReload(() => import('./pages/Workbench'));
const Map = lazyWithReload(() => import('./pages/CityEventMap'));
const Calendar = lazyWithReload(() => import('./pages/EventCalendar'));
const Agenda = lazyWithReload(() => import('./pages/EventAgenda'));
const Venues = lazyWithReload(() => import('./pages/VenueIndex'));
const PrivateData = lazyWithReload(() => import('./pages/PrivateData'));
const Graph = lazyWithReload(() => import('./pages/KnowledgeGraph'));
const Hotels = lazyWithReload(() => import('./pages/HotelIntelligence'));
const HotelFinder = lazyWithReload(() => import('./pages/HotelFinder'));
const Insights = lazyWithReload(() => import('./pages/DistrictInsights'));
const DataQuality = lazyWithReload(() => import('./pages/DataQuality'));
const Login = lazyWithReload(() => import('./pages/Login'));
const Register = lazyWithReload(() => import('./pages/Register'));
const ReviewConsole = lazyWithReload(() => import('./pages/ReviewConsole'));

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

export default function App({ initialAccount }: { initialAccount?: AccountState }) {
  // Identity: the operator side (HTTP Basic) — hides the review console from visitors.
  // Account: the customer side (session cookie) — decides which paid workflow is unlocked.
  // Neither is the enforcement point for writes: backend/auth.py checks operator roles and
  // backend/accounts.py derives the customer plan from the dates on every request.
  return (
    <IdentityProvider>
      <AccountProvider initialState={initialAccount}>
        <PlatformLayout>
          <Suspense fallback={<div className="loading-page"><Spin size="large"/></div>}>
            <Routes>
              <Route path="/workbench" element={<Page name="本店工作台"><Workbench /></Page>}/>
              <Route path="/map" element={<Page name="城市活动地图"><Map /></Page>}/>
              <Route path="/calendar" element={<Page name="活动日历"><Calendar /></Page>}/>
              <Route path="/agenda" element={<Page name="活动清单"><Agenda /></Page>}/>
              <Route path="/venues" element={<Page name="场馆活动清单"><Venues /></Page>}/>
          <Route path="/private" element={<Page name="本店经营数据"><PrivateData /></Page>}/>
              <Route path="/graph" element={<Page name="知识图谱"><Graph /></Page>}/>
              {/* The commercial edition is paused, so these two are ordinary pages rather than
                  gated ones. FILING_MODE still redirects them during the ICP review, which asks
                  for a non-commercial information site. */}
              <Route path="/hotels" element={FILING_MODE ? <Navigate to="/map" replace/> : <Page name="酒店活动情报"><Hotels /></Page>}/>
              <Route path="/find-hotels" element={FILING_MODE ? <Navigate to="/map" replace/> : <Page name="找酒店"><HotelFinder /></Page>}/>
              <Route path="/insights" element={FILING_MODE ? <Navigate to="/map" replace/> : <Page name="商圈洞察"><Insights /></Page>}/>
              <Route path="/evidence" element={<Page name="数据质量与来源"><DataQuality /></Page>}/>
              {/* The plan page is off the product while there is no paid tier; keeping the route
                  would leave a pricing screen reachable from links nobody can see. */}
              <Route path="/plans" element={<Navigate to="/map" replace/>}/>
              <Route path="/login" element={FILING_MODE ? <Navigate to="/map" replace/> : <Page name="登录"><Login /></Page>}/>
              <Route path="/register" element={FILING_MODE ? <Navigate to="/map" replace/> : <Page name="注册"><Register /></Page>}/>
              <Route path="/review" element={<Page name="审核台"><ReviewConsole /></Page>}/>
              <Route path="*" element={<Navigate to="/map" replace/>}/>
            </Routes>
          </Suspense>
          {/* The event drawer renders outside the routes, so it needs its own boundary too. */}
          <ErrorBoundary where="活动详情">
            <EventDetail />
          </ErrorBoundary>
        </PlatformLayout>
      </AccountProvider>
    </IdentityProvider>
  );
}
