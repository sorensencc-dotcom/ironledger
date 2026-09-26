import React, { useState } from 'react';
import {
  Plug,
  RefreshCw,
  ShieldCheck,
  Clock,
  Activity,
  AlertTriangle,
  Play,
  Key,
  CheckCircle2,
  Radio,
} from 'lucide-react';
import type {
  ConnectorCredentialStatus,
  ConnectorProvider,
  ConnectorSyncRun,
  SyncTimelineEvent,
} from '../types';

interface ConnectorsViewProps {
  providers: ConnectorProvider[];
  credentials: ConnectorCredentialStatus[];
  syncRuns: ConnectorSyncRun[];
  timeline: SyncTimelineEvent[];
  onTriggerSync: (providerId: string) => Promise<void>;
  onRefresh: () => void;
  loading: boolean;
}

export const ConnectorsView: React.FC<ConnectorsViewProps> = ({
  providers,
  credentials,
  syncRuns,
  timeline,
  onTriggerSync,
  onRefresh,
  loading,
}) => {
  const [triggeringProvider, setTriggeringProvider] = useState<string | null>(null);

  const handleTrigger = async (providerId: string) => {
    setTriggeringProvider(providerId);
    try {
      await onTriggerSync(providerId);
    } finally {
      setTriggeringProvider(null);
    }
  };

  const getBreakerBadge = (state: string) => {
    switch (state) {
      case 'CLOSED':
        return (
          <span className="px-2 py-0.5 rounded-none text-[10px] font-bold bg-[#132a1c] text-[#8fc79e] border border-[#1d442b] flex items-center gap-1 font-mono">
            <CheckCircle2 className="w-3 h-3 text-[#8fc79e]" />
            CIRCUIT CLOSED
          </span>
        );
      case 'OPEN':
        return (
          <span className="px-2 py-0.5 rounded-none text-[10px] font-bold bg-[#2c120e] text-[#e2765f] border border-[#4a1c14] flex items-center gap-1 animate-pulse font-mono">
            <AlertTriangle className="w-3 h-3 text-[#e2765f]" />
            CIRCUIT OPEN
          </span>
        );
      case 'HALF_OPEN':
        return (
          <span className="px-2 py-0.5 rounded-none text-[10px] font-bold bg-[#2a1d0d] text-[#e0a84c] border border-[#4a3518] flex items-center gap-1 font-mono">
            <Radio className="w-3 h-3 text-[#e0a84c]" />
            HALF-OPEN
          </span>
        );
      default:
        return null;
    }
  };

  const getFreshnessBadge = (status: string) => {
    switch (status) {
      case 'FRESH':
        return <span className="text-[10px] px-1.5 py-0.5 rounded-none bg-[#132a1c] text-[#8fc79e] border border-[#1d442b] font-bold font-mono">FRESH (&lt;30d)</span>;
      case 'STALE':
        return <span className="text-[10px] px-1.5 py-0.5 rounded-none bg-[#2a1d0d] text-[#e0a84c] border border-[#4a3518] font-bold font-mono">STALE (&gt;30d)</span>;
      case 'EXPIRED':
        return <span className="text-[10px] px-1.5 py-0.5 rounded-none bg-[#2c120e] text-[#e2765f] border border-[#4a1c14] font-bold font-mono">EXPIRED (&gt;90d)</span>;
      default:
        return <span className="text-[10px] px-1.5 py-0.5 rounded-none bg-[#1a1410] text-[#7a6e65] border border-[#2c2420] font-mono">UNSET</span>;
    }
  };

  return (
    <div className="flex-1 p-6 overflow-y-auto space-y-6 font-mono text-xs bg-[#0d0a08] relative">
      <div className="ghost-watermark text-[6rem] top-4 right-3 select-none pointer-events-none">
        CONNECTORS
      </div>
      <div style={{ position: 'absolute', top: '-60px', right: '-40px', width: '260px', height: '260px', background: 'radial-gradient(circle, rgba(139,58,26,0.22), transparent 70%)', filter: 'blur(30px)', pointerEvents: 'none', zIndex: 0 }} />

      {/* Header */}
      <div className="flex items-center justify-between border-b border-[#2c2420] pb-3 relative z-10">
        <div>
          <h2 className="text-base font-serif font-bold text-[#f2ece2] flex items-center gap-2">
            <Plug className="w-4 h-4 text-[#b8922a]" />
            Connector Governance & Ingestion Dashboard
          </h2>
          <p className="text-[#7a6e65] text-xs">
            Multi-protocol banking connectors, envelope credential vaults, and circuit breaker health
          </p>
        </div>
        <button
          onClick={onRefresh}
          disabled={loading}
          className="px-3 py-1 rounded-none bg-[#1a1410] hover:bg-[#241c16] text-[#e8dfd1] border border-[#3a2e26] flex items-center gap-1.5 transition-colors text-xs font-mono uppercase tracking-wider disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-[#c4501a]' : 'text-[#b8922a]'}`} />
          <span>Refresh</span>
        </button>
      </div>

      {/* Provider Governance Cards */}
      <div className="space-y-3 relative z-10">
        <h3 className="text-xs font-bold text-[#b8922a] font-sans uppercase tracking-wider flex items-center gap-2">
          <Radio className="w-3.5 h-3.5 text-[#b8922a]" />
          Registered Providers ({providers.length})
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
          {providers.map((p) => {
            const cred = credentials.find((c) => c.provider_id === p.provider_id);
            const isTriggering = triggeringProvider === p.provider_id;
            return (
              <div
                key={p.provider_id}
                className="p-4 rounded-none bg-[#1a1410] border border-[#2c2420] flex flex-col justify-between space-y-3 hover:border-[#3a2e26] transition-colors"
              >
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="px-1.5 py-0.5 rounded-none bg-[#241c16] text-[#b8922a] border border-[#3a2e26] font-bold text-[10px] font-mono">
                      {p.protocol_type}
                    </span>
                    {getBreakerBadge(p.circuit_breaker_state)}
                  </div>
                  <div>
                    <h4 className="font-serif font-bold text-sm text-[#f2ece2]">{p.name}</h4>
                    <p className="text-[11px] text-[#7a6e65] truncate font-mono">{p.base_url}</p>
                  </div>
                  <div className="pt-1 border-t border-[#2c2420] grid grid-cols-2 gap-2 text-[10px] text-[#7a6e65]">
                    <div>Rate Limit: <span className="text-[#e8dfd1] font-bold">{p.rate_limit_rpm} RPM</span></div>
                    <div>Burst: <span className="text-[#e8dfd1] font-bold">{p.burst_capacity} req</span></div>
                  </div>
                </div>

                <div className="pt-2 border-t border-[#2c2420] flex items-center justify-between">
                  <div className="flex items-center gap-1.5 text-[10px]">
                    <Key className="w-3 h-3 text-[#7a6e65]" />
                    {cred?.has_credentials ? (
                      <span className="text-[#8fc79e] font-bold">Enveloped</span>
                    ) : (
                      <span className="text-[#e0a84c]">No Key</span>
                    )}
                  </div>
                  <button
                    onClick={() => handleTrigger(p.provider_id)}
                    disabled={isTriggering || p.circuit_breaker_state === 'OPEN'}
                    className="px-2.5 py-1 rounded-none bg-[#c4501a] hover:bg-[#d4622b] text-[#f2ece2] font-mono text-[11px] uppercase font-bold flex items-center gap-1 shadow-sm transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                    title={p.circuit_breaker_state === 'OPEN' ? 'Circuit breaker is OPEN' : 'Execute immediate ingestion run'}
                  >
                    {isTriggering ? (
                      <RefreshCw className="w-3 h-3 animate-spin" />
                    ) : (
                      <Play className="w-3 h-3" />
                    )}
                    <span>Trigger</span>
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Credential Vault Status Panel */}
      <div className="space-y-3 relative z-10">
        <h3 className="text-xs font-bold text-[#b8922a] font-sans uppercase tracking-wider flex items-center gap-2">
          <ShieldCheck className="w-3.5 h-3.5 text-[#8fc79e]" />
          Envelope Encryption Vault Status
        </h3>
        <div className="border border-[#2c2420] rounded-none bg-[#1a1410] divide-y divide-[#2c2420]/60 p-2">
          {credentials.map((c) => (
            <div key={c.provider_id} className="py-2.5 px-2 flex items-center justify-between hover:bg-[#241c16]/60 rounded-none transition-colors">
              <div className="flex items-center gap-3">
                <span className="font-bold text-[#f2ece2] font-mono">{c.provider_id}</span>
                <span className="text-[#7a6e65] text-[11px]">
                  KEK: <span className="text-[#b8922a] font-mono">{c.kek_key_id || 'None'}</span>
                </span>
                <span className="text-[#7a6e65] text-[11px]">
                  DEK Age: <span className="text-[#e8dfd1] font-bold">{c.dek_rotation_age_days}d</span>
                </span>
              </div>
              <div>{getFreshnessBadge(c.iv_freshness_status)}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Sync Execution Timeline */}
      <div className="space-y-3 relative z-10">
        <h3 className="text-xs font-bold text-[#b8922a] font-sans uppercase tracking-wider flex items-center gap-2">
          <Activity className="w-3.5 h-3.5 text-[#b8922a]" />
          Sync Execution Timeline
        </h3>
        <div className="border border-[#2c2420] rounded-none bg-[#1a1410] p-3 space-y-2">
          {timeline.length === 0 ? (
            <div className="text-center text-[#7a6e65] py-3">No sync events recorded in the active timeline.</div>
          ) : (
            timeline.map((ev) => (
              <div key={ev.event_id} className="flex items-start gap-3 text-xs py-1.5 border-b border-[#2c2420]/60 last:border-0">
                <Clock className="w-3.5 h-3.5 text-[#b8922a] shrink-0 mt-0.5" />
                <div className="flex-1 flex items-center justify-between">
                  <div>
                    <span className="font-bold text-[#f2ece2] mr-2">{ev.provider_id}</span>
                    <span className="text-[#a89e94]">{ev.summary}</span>
                  </div>
                  <span className="text-[10px] text-[#7a6e65] font-mono">{ev.timestamp_utc}</span>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Recent Sync Runs Table */}
      <div className="space-y-3 relative z-10">
        <h3 className="text-xs font-bold text-[#b8922a] font-sans uppercase tracking-wider flex items-center gap-2">
          <Clock className="w-3.5 h-3.5 text-[#7a6e65]" />
          Recent Ingestion Runs ({syncRuns.length})
        </h3>
        <div className="border border-[#2c2420] rounded-none bg-[#1a1410] overflow-hidden">
          <table className="w-full text-left divide-y divide-[#2c2420]/60">
            <thead className="bg-[#241c16] text-[10px] text-[#7a6e65] font-sans font-bold uppercase tracking-wider">
              <tr>
                <th className="px-3 py-2">Run ID</th>
                <th className="px-3 py-2">Provider</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Fetched</th>
                <th className="px-3 py-2">Staged</th>
                <th className="px-3 py-2">Started (UTC)</th>
                <th className="px-3 py-2">Error</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#2c2420]/40 text-[11px]">
              {syncRuns.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-3 py-4 text-center text-[#7a6e65]">
                    No synchronization runs recorded.
                  </td>
                </tr>
              ) : (
                syncRuns.map((r) => (
                  <tr key={r.run_id} className="hover:bg-[#241c16]/50 transition-colors">
                    <td className="px-3 py-2 font-mono text-[#a89e94]">{r.run_id.slice(0, 10)}</td>
                    <td className="px-3 py-2 font-bold text-[#f2ece2]">{r.provider_id}</td>
                    <td className="px-3 py-2">
                      <span
                        className={`px-1.5 py-0.5 rounded-none text-[10px] font-bold font-mono ${
                          r.status === 'SUCCESS'
                            ? 'bg-[#132a1c] text-[#8fc79e] border border-[#1d442b]'
                            : r.status === 'RUNNING'
                            ? 'bg-[#2c1a14] text-[#c4501a] border border-[#c4501a] animate-pulse'
                            : 'bg-[#2c120e] text-[#e2765f] border border-[#4a1c14]'
                        }`}
                      >
                        {r.status}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-[#a89e94]">{r.records_fetched}</td>
                    <td className="px-3 py-2 text-[#f2ece2] font-bold">{r.records_staged}</td>
                    <td className="px-3 py-2 text-[#7a6e65] font-mono text-[10px]">{r.started_at_utc}</td>
                    <td className="px-3 py-2 text-[#e2765f] truncate max-w-xs">{r.error_code || '—'}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
