import { Routes, Route, Navigate } from 'react-router-dom';
import { Suspense, lazy } from 'react';
import { Spin } from 'antd';
import PlatformLayout from './components/Layout';
import EventDetail from './components/EventDetail';
const Map = lazy(() => import('./pages/CityEventMap'));
const Calendar = lazy(() => import('./pages/EventCalendar'));
const Graph = lazy(() => import('./pages/KnowledgeGraph'));
const Hotels = lazy(() => import('./pages/HotelIntelligence'));
const Insights = lazy(() => import('./pages/DistrictInsights'));
const Evidence = lazy(() => import('./pages/EvidenceQuality'));
export default function App() { return <PlatformLayout><Suspense fallback={<div className="loading-page"><Spin size="large"/></div>}><Routes><Route path="/map" element={<Map />}/><Route path="/calendar" element={<Calendar />}/><Route path="/graph" element={<Graph />}/><Route path="/hotels" element={<Hotels />}/><Route path="/insights" element={<Insights />}/><Route path="/evidence" element={<Evidence />}/><Route path="*" element={<Navigate to="/map" replace/>}/></Routes></Suspense><EventDetail /></PlatformLayout>; }
