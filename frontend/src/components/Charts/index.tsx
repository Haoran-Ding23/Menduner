import { useEffect, useRef } from 'react';
import * as echarts from 'echarts';
export default function Chart({ option, onClick }: {
    option: echarts.EChartsOption;
    onClick?: (name: string) => void;
}) { const ref = useRef<HTMLDivElement>(null); useEffect(() => { if (!ref.current)
    return; const chart = echarts.init(ref.current); chart.setOption(option); chart.on('click', p => onClick?.(String(p.name))); const resize = () => chart.resize(); const observer = new ResizeObserver(resize); observer.observe(ref.current); return () => { observer.disconnect(); chart.dispose(); }; }, [option, onClick]); return <div className="chart" ref={ref} role="img" aria-label="点击图表筛选活动"/>; }
