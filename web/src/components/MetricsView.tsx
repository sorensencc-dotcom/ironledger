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
    <div className="flex-1 p-6 overflow-y-auto space-y-6 font-mono text-xs bg-[#0d0a08] relative">
      <div className="ghost-watermark text-[6rem] -top-8 -right-4 select-none pointer-events-none">
        METRICS
      </div>

      {/* Header */}
      <div className="flex items-center justify-between border-b border-[#2c2420] pb-3 relative z-10">
        <div>
          <h2 className="text-base font-serif font-bold text-[#f2ece2] flex items-center gap-2">
            <BarChart3 className="w-4 h-4 text-[#b8922a]" />
            System Observability & OpenMetrics Telemetry
          </h2>
          <p className="text-[#7a6e65] text-xs">
            Live Prometheus metrics telemetry scraper (/metrics) with subsystem gauges
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowRaw(!showRaw)}
            className="px-3 py-1 rounded-none bg-[#1a1410] hover:bg-[#241c16] text-[#e8dfd1] border border-[#3a2e26] flex items-center gap-1.5 transition-colors text-xs font-mono uppercase tracking-wider"
          >
            <Code className="w-3.5 h-3.5 text-[#b8922a]" />
            <span>{showRaw ? 'Structured View' : 'Raw OpenMetrics'}</span>
          </button>
          <button
            onClick={onRefresh}
            disabled={loading}
            className="px-3 py-1 rounded-none bg-[#1a1410] hover:bg-[#241c16] text-[#e8dfd1] border border-[#3a2e26] flex items-center gap-1.5 transition-colors text-xs font-mono uppercase tracking-wider disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-[#c4501a]' : 'text-[#b8922a]'}`} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {showRaw ? (
        <div className="border border-[#2c2420] rounded-none bg-[#0d0a08] p-4 font-mono text-xs overflow-x-auto text-[#8fc79e] whitespace-pre relative z-10">
          {rawMetrics || '# No metrics payload available'}
        </div>
      ) : (
        <>
          {/* Top Key Stat Cards */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3 relative z-10">
            <div className="p-4 rounded-none bg-[#1a1410] border border-[#2c2420] border-l-2 border-l-[#b8922a] space-y-1">
              <div className="flex items-center justify-between text-[#7a6e65] text-[10px] uppercase font-sans font-bold tracking-wider">
                <span>Total HTTP Requests</span>
                <Server className="w-3.5 h-3.5 text-[#b8922a]" />
              </div>
              <div className="text-xl font-bold font-mono text-[#f2ece2]">{requestCount}</div>
              <div className="text-[10px] text-[#8fc79e] font-mono">Endpoint Throughput</div>
            </div>

            <div className="p-4 rounded-none bg-[#1a1410] border border-[#2c2420] border-l-2 border-l-[#e2765f] space-y-1">
              <div className="flex items-center justify-between text-[#7a6e65] text-[10px] uppercase font-sans font-bold tracking-wider">
                <span>Error Count (4xx/5xx)</span>
                <Activity className="w-3.5 h-3.5 text-[#e2765f]" />
              </div>
              <div className="text-xl font-bold font-mono text-[#f2ece2]">{errorCount}</div>
              <div className="text-[10px] text-[#7a6e65] font-mono">
                {requestCount > 0 ? `${((errorCount / requestCount) * 100).toFixed(1)}% error rate` : '0% error rate'}
              </div>
            </div>

            <div className="p-4 rounded-none bg-[#1a1410] border border-[#2c2420] border-l-2 border-l-[#c4501a] space-y-1">
              <div className="flex items-center justify-between text-[#7a6e65] text-[10px] uppercase font-sans font-bold tracking-wider">
                <span>Connector Syncs</span>
                <Zap className="w-3.5 h-3.5 text-[#c4501a]" />
              </div>
              <div className="text-xl font-bold font-mono text-[#f2ece2]">{syncCount}</div>
              <div className="text-[10px] text-[#b8922a] font-mono">Sync Pipeline Runs</div>
            </div>

            <div className="p-4 rounded-none bg-[#1a1410] border border-[#2c2420] border-l-2 border-l-[#8fc79e] space-y-1">
              <div className="flex items-center justify-between text-[#7a6e65] text-[10px] uppercase font-sans font-bold tracking-wider">
                <span>Webhook Deliveries</span>
                <Gauge className="w-3.5 h-3.5 text-[#8fc79e]" />
              </div>
              <div className="text-xl font-bold font-mono text-[#f2ece2]">{webhookDeliveryCount}</div>
              <div className="text-[10px] text-[#8fc79e] font-mono">Outbox Dispatches</div>
            </div>
          </div>

          {/* Metric Breakdown Feed */}
          <div className="space-y-3 relative z-10">
            <h3 className="text-xs font-bold text-[#b8922a] font-sans uppercase tracking-wider flex items-center gap-2">
              <Activity className="w-3.5 h-3.5 text-[#b8922a]" />
              Active Telemetry Gauges ({Object.keys(metricsMap).length})
            </h3>
            <div className="border border-[#2c2420] rounded-none bg-[#1a1410] divide-y divide-[#2c2420]/60 p-2">
              {Object.keys(metricsMap).length === 0 ? (
                <div className="p-4 text-center text-[#7a6e65]">No telemetry values loaded yet.</div>
              ) : (
                Object.entries(metricsMap).map(([metricName, val]) => (
                  <div key={metricName} className="py-2 px-2 flex items-center justify-between hover:bg-[#241c16]/60 rounded-none transition-colors text-xs">
                    <span className="font-mono text-[#a89e94] truncate max-w-xl">{metricName}</span>
                    <span className="font-mono font-bold text-[#b8922a]">{val}</span>
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
