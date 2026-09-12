import React, { useState } from 'react';
import {
  BarChart3,
  RefreshCw,
  Activity,
  Zap,
  Server,
  Code,
  Gauge,
} from 'lucide-react';

interface MetricsViewProps {
  rawMetrics: string;
  onRefresh: () => void;
  loading: boolean;
}

export const MetricsView: React.FC<MetricsViewProps> = ({
  rawMetrics,
  onRefresh,
  loading,
}) => {
  const [showRaw, setShowRaw] = useState(false);

  // Parse key metrics from Prometheus format
  const parseMetrics = (text: string) => {
    const lines = text.split('\n');
    const parsed: Record<string, number> = {};

    lines.forEach((line) => {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) return;
      const parts = trimmed.split(/\s+/);
      if (parts.length >= 2) {
        const key = parts[0];
        const val = parseFloat(parts[1]);
        if (!isNaN(val)) {
          parsed[key] = val;
        }
      }
    });
    return parsed;
  };

  const metricsMap = parseMetrics(rawMetrics);

  const requestCount = Object.entries(metricsMap)
    .filter(([k]) => k.startsWith('http_requests_total'))
    .reduce((acc, [, v]) => acc + v, 0);

  const errorCount = Object.entries(metricsMap)
    .filter(([k]) => k.startsWith('http_requests_total') && (k.includes('status="5') || k.includes('status="4')))
    .reduce((acc, [, v]) => acc + v, 0);

  const syncCount = Object.entries(metricsMap)
    .filter(([k]) => k.startsWith('connector_sync_runs_total'))
    .reduce((acc, [, v]) => acc + v, 0);

  const webhookDeliveryCount = Object.entries(metricsMap)
    .filter(([k]) => k.startsWith('webhook_deliveries_total'))
    .reduce((acc, [, v]) => acc + v, 0);

  return (
    <div className="flex-1 p-6 overflow-y-auto space-y-6 font-mono text-xs">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-800 pb-3">
        <div>
          <h2 className="text-base font-bold text-slate-100 flex items-center gap-2">
            <BarChart3 className="w-4 h-4 text-indigo-400" />
            System Observability & OpenMetrics Telemetry
          </h2>
          <p className="text-slate-500 text-xs">
            Live Prometheus metrics telemetry scraper (/metrics) with subsystem gauges
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowRaw(!showRaw)}
            className="px-3 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 flex items-center gap-1.5 transition-colors text-xs"
          >
            <Code className="w-3.5 h-3.5 text-indigo-400" />
            <span>{showRaw ? 'Structured View' : 'Raw OpenMetrics'}</span>
          </button>
          <button
            onClick={onRefresh}
            disabled={loading}
            className="px-3 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 flex items-center gap-1.5 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {showRaw ? (
        <div className="border border-slate-800 rounded bg-slate-950 p-4 font-mono text-xs overflow-x-auto text-emerald-400/90 whitespace-pre">
          {rawMetrics || '# No metrics payload available'}
        </div>
      ) : (
        <>
          {/* Top Key Stat Cards */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
            <div className="p-4 rounded bg-slate-800/60 border border-slate-700/60 space-y-1">
              <div className="flex items-center justify-between text-slate-400 text-[10px] uppercase">
                <span>Total HTTP Requests</span>
                <Server className="w-3.5 h-3.5 text-indigo-400" />
              </div>
              <div className="text-xl font-bold text-slate-100">{requestCount}</div>
              <div className="text-[10px] text-emerald-400">Endpoint Throughput</div>
            </div>

            <div className="p-4 rounded bg-slate-800/60 border border-slate-700/60 space-y-1">
              <div className="flex items-center justify-between text-slate-400 text-[10px] uppercase">
                <span>Error Count (4xx/5xx)</span>
                <Activity className="w-3.5 h-3.5 text-rose-400" />
              </div>
              <div className="text-xl font-bold text-slate-100">{errorCount}</div>
              <div className="text-[10px] text-slate-500">
                {requestCount > 0 ? `${((errorCount / requestCount) * 100).toFixed(1)}% error rate` : '0% error rate'}
              </div>
            </div>

            <div className="p-4 rounded bg-slate-800/60 border border-slate-700/60 space-y-1">
              <div className="flex items-center justify-between text-slate-400 text-[10px] uppercase">
                <span>Connector Syncs</span>
                <Zap className="w-3.5 h-3.5 text-amber-400" />
              </div>
              <div className="text-xl font-bold text-slate-100">{syncCount}</div>
              <div className="text-[10px] text-indigo-300">Sync Pipeline Runs</div>
            </div>

            <div className="p-4 rounded bg-slate-800/60 border border-slate-700/60 space-y-1">
              <div className="flex items-center justify-between text-slate-400 text-[10px] uppercase">
                <span>Webhook Deliveries</span>
                <Gauge className="w-3.5 h-3.5 text-emerald-400" />
              </div>
              <div className="text-xl font-bold text-slate-100">{webhookDeliveryCount}</div>
              <div className="text-[10px] text-emerald-400">Outbox Dispatches</div>
            </div>
          </div>

          {/* Metric Breakdown Feed */}
          <div className="space-y-3">
            <h3 className="text-xs font-bold text-slate-300 uppercase tracking-wider flex items-center gap-2">
              <Activity className="w-3.5 h-3.5 text-indigo-400" />
              Active Telemetry Gauges ({Object.keys(metricsMap).length})
            </h3>
            <div className="border border-slate-800 rounded bg-slate-900/60 divide-y divide-slate-800/60 p-2">
              {Object.keys(metricsMap).length === 0 ? (
                <div className="p-4 text-center text-slate-500">No telemetry values loaded yet.</div>
              ) : (
                Object.entries(metricsMap).map(([metricName, val]) => (
                  <div key={metricName} className="py-2 px-2 flex items-center justify-between hover:bg-slate-800/40 rounded transition-colors text-xs">
                    <span className="font-mono text-slate-300 truncate max-w-xl">{metricName}</span>
                    <span className="font-mono font-bold text-indigo-300">{val}</span>
                  </div>
                ))
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
};
