import { useState, useEffect } from 'react';
import { Activity, Clock, ShieldCheck, Newspaper, ShieldAlert } from 'lucide-react';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler
} from 'chart.js';
import { Line } from 'react-chartjs-2';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler
);

function App() {
  const [status, setStatus] = useState(null);
  const [claims, setClaims] = useState([]);
  const [metrics, setMetrics] = useState([]);
  const [credibility, setCredibility] = useState([]);
  const [health, setHealth] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [statusRes, claimsRes, metricsRes, credRes, healthRes] = await Promise.all([
          fetch('/status'),
          fetch('/claims?hours=24&limit=50'),
          fetch('/metrics'),
          fetch('/api/sources/credibility'),
          fetch('/api/sources/health')
        ]);
        
        if (statusRes.ok) setStatus(await statusRes.json());
        if (claimsRes.ok) {
          const c = await claimsRes.json();
          setClaims(c.claims || []);
        }
        if (metricsRes.ok) {
          const m = await metricsRes.json();
          setMetrics(m.metrics || []);
        }
        if (credRes.ok) setCredibility(await credRes.json());
        if (healthRes.ok) setHealth(await healthRes.json());
      } catch (e) {
        console.error('Failed to fetch data', e);
      } finally {
        setLoading(false);
      }
    };
    
    fetchData();
    const interval = setInterval(fetchData, 60000);
    return () => clearInterval(interval);
  }, []);

  const triggerFetch = async () => {
    try {
      await fetch('/trigger', { method: 'POST' });
      alert('Fetch cycle triggered manually!');
    } catch (e) {
      alert('Trigger failed: ' + e.message);
    }
  };

  if (loading && !status) {
    return <div className="min-h-screen flex items-center justify-center text-white">Loading Agent Data...</div>;
  }

  const isOnline = status?.status === 'running';
  const fetchJob = status?.scheduled_jobs?.find(j => j.id === 'fetch_and_verify');
  const nextFetchStr = fetchJob?.next_run ? new Date(fetchJob.next_run).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}) : 'Unknown';

  // Chart Data
  const chartData = {
    labels: metrics.filter(m => m.event_type === 'fetch_cycle').map(m => new Date(m.timestamp).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})).reverse(),
    datasets: [
      {
        label: 'Latency (ms)',
        data: metrics.filter(m => m.event_type === 'fetch_cycle').map(m => m.latency_ms).reverse(),
        borderColor: '#764ba2',
        backgroundColor: 'rgba(118, 75, 162, 0.2)',
        fill: true,
        yAxisID: 'y',
        tension: 0.4
      },
      {
        label: 'Volume (Articles)',
        data: metrics.filter(m => m.event_type === 'fetch_cycle').map(m => m.llm_cost).reverse(),
        borderColor: '#4CAF50',
        backgroundColor: 'rgba(76, 175, 80, 0.2)',
        borderDash: [5, 5],
        yAxisID: 'y1',
        tension: 0.4
      }
    ]
  };

  return (
    <div className="max-w-7xl mx-auto py-10 px-4 sm:px-6 lg:px-8 space-y-8">
      
      {/* Header */}
      <header className="flex flex-col md:flex-row justify-between items-center gap-4">
        <div>
          <h1 className="text-4xl font-bold text-gradient mb-2">Daily News Agent</h1>
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-2 px-3 py-1 rounded-full bg-green-500/10 border border-green-500/30 text-green-400 text-sm">
              <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse"></span>
              {isOnline ? 'Online' : 'Offline'}
            </span>
            <span className="text-sm text-gray-400">Next fetch at {nextFetchStr}</span>
          </div>
        </div>
        <button 
          onClick={triggerFetch}
          className="px-6 py-2.5 rounded-lg bg-gradient-to-r from-[#667eea] to-[#764ba2] text-white font-medium hover:opacity-90 transition shadow-lg flex items-center gap-2"
        >
          <Activity size={18} /> Force Fetch Cycle
        </button>
      </header>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        <div className="glass-card">
          <div className="text-gray-400 text-sm mb-1 flex items-center gap-2"><Newspaper size={16}/> Articles Today</div>
          <div className="text-3xl font-bold text-gradient">{status?.today?.total_articles || 0}</div>
        </div>
        <div className="glass-card">
          <div className="text-gray-400 text-sm mb-1 flex items-center gap-2"><ShieldCheck size={16}/> Verified Claims</div>
          <div className="text-3xl font-bold text-green-400">{status?.today?.verified || 0}</div>
        </div>
        <div className="glass-card">
          <div className="text-gray-400 text-sm mb-1 flex items-center gap-2"><Clock size={16}/> Covered Categories</div>
          <div className="text-3xl font-bold text-blue-400">{status?.today?.categories?.length || 0}</div>
        </div>
        <div className="glass-card">
          <div className="text-gray-400 text-sm mb-1 flex items-center gap-2"><ShieldAlert size={16}/> Degraded Sources</div>
          <div className="text-3xl font-bold text-red-400">{health.filter(h => h.is_degraded).length || 0}</div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        
        {/* Main Feed */}
        <div className="lg:col-span-2 space-y-6">
          <div className="glass-panel p-6">
            <h2 className="text-xl font-semibold mb-6 flex items-center gap-2"><Activity className="text-[#667eea]" /> Live Hype & Latency</h2>
            <div className="h-64">
              <Line 
                data={chartData} 
                options={{
                  responsive: true,
                  maintainAspectRatio: false,
                  scales: {
                    x: { display: false },
                    y: { type: 'linear', position: 'left', grid: { color: 'rgba(255,255,255,0.05)' } },
                    y1: { type: 'linear', position: 'right', grid: { drawOnChartArea: false } }
                  }
                }} 
              />
            </div>
          </div>

          <div className="glass-panel p-6">
            <h2 className="text-xl font-semibold mb-6 flex items-center gap-2"><Newspaper className="text-[#667eea]"/> Live Cluster Feed</h2>
            <div className="space-y-4">
              {claims.length === 0 ? <p className="text-gray-400 text-center py-10">No stories yet today.</p> : claims.map(c => (
                <div key={c.id} className="p-4 rounded-xl bg-white/5 border border-white/5 hover:border-white/10 transition">
                  <h3 className="font-medium text-lg mb-2">
                    <a href={c.url} target="_blank" rel="noreferrer" className="hover:text-blue-300">{c.title}</a>
                  </h3>
                  <div className="flex flex-wrap gap-2 items-center">
                    <span className="tag border-white/20 text-gray-300">{c.category || 'General'}</span>
                    <span className={`tag ${c.confidence >= 80 ? 'tag-green' : c.confidence >= 50 ? 'tag-yellow' : 'tag-red'}`}>
                      {c.confidence >= 80 ? '🟢' : c.confidence >= 50 ? '🟡' : '🔴'} {c.confidence}%
                    </span>
                    {(() => {
                       try {
                         const tickers = typeof c.tickers === 'string' ? JSON.parse(c.tickers) : (c.tickers || []);
                         return tickers.slice(0,3).map(t => <span key={t} className="tag tag-blue">{t}</span>);
                       } catch { return null; }
                    })()}
                    <span className="text-xs text-gray-500 ml-auto">{c.source}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Sidebar */}
        <div className="space-y-8">
          
          {/* Source Credibility */}
          <div className="glass-panel p-6">
            <h2 className="text-lg font-semibold mb-4 flex items-center gap-2"><ShieldCheck className="text-green-400"/> Source Credibility</h2>
            <div className="space-y-3">
              {credibility.length === 0 ? <p className="text-gray-400 text-sm">No data yet.</p> : credibility.map(c => (
                <div key={c.source_domain} className="flex justify-between items-center text-sm border-b border-white/5 pb-2 last:border-0">
                  <span className="truncate flex-1 text-gray-300 pr-2">{c.source_domain}</span>
                  <div className="flex items-center gap-3">
                    <span className="text-gray-500 text-xs">{c.total_articles} arts</span>
                    <span className={`font-semibold ${c.credibility_score >= 60 ? 'text-green-400' : c.credibility_score <= 40 ? 'text-red-400' : 'text-yellow-400'}`}>
                      {Math.round(c.credibility_score)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Self-Healing Status */}
          <div className="glass-panel p-6">
            <h2 className="text-lg font-semibold mb-4 flex items-center gap-2"><Activity className="text-[#764ba2]"/> Self-Healing Status</h2>
            <div className="space-y-3">
              {health.length === 0 ? <p className="text-gray-400 text-sm">All sources healthy.</p> : health.map(h => {
                const isDegraded = h.is_degraded || h.consecutive_failures >= 3;
                return (
                  <div key={h.source_id} className="flex flex-col text-sm border-b border-white/5 pb-2 last:border-0">
                    <div className="flex justify-between items-center mb-1">
                      <span className="truncate flex-1 font-medium text-gray-200">{h.source_id}</span>
                      {isDegraded ? (
                        <span className="tag tag-red">Degraded</span>
                      ) : h.consecutive_failures > 0 ? (
                        <span className="tag tag-yellow">Failing ({h.consecutive_failures})</span>
                      ) : (
                        <span className="tag tag-green">Healthy</span>
                      )}
                    </div>
                    {h.consecutive_failures > 0 && (
                      <div className="text-xs text-gray-400">
                        Backoff until: {new Date(h.next_attempt_at).toLocaleTimeString()}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}

export default App;
