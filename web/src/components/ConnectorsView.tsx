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
          <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-950 text-emerald-300 border border-emerald-800/80 flex items-center gap-1">
            <CheckCircle2 className="w-3 h-3 text-emerald-400" />
            CIRCUIT CLOSED
          </span>
        );
      case 'OPEN':
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-rose-950 text-rose-300 border border-rose-800/80 flex items-center gap-1 animate-pulse">
            <AlertTriangle className="w-3 h-3 text-rose-400" />
            CIRCUIT OPEN
          </span>
        );
      case 'HALF_OPEN':
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-950 text-amber-300 border border-amber-800/80 flex items-center gap-1">
            <Radio className="w-3 h-3 text-amber-400" />
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
        return <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-950 text-emerald-400 border border-emerald-800 font-bold">FRESH (&lt;30d)</span>;
      case 'STALE':
        return <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-950 text-amber-400 border border-amber-800 font-bold">STALE (&gt;30d)</span>;
      case 'EXPIRED':
        return <span className="text-[10px] px-1.5 py-0.5 rounded bg-rose-950 text-rose-400 border border-rose-800 font-bold">EXPIRED (&gt;90d)</span>;
      default:
        return <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">UNSET</span>;
    }
  };

  return (
    <div className="flex-1 p-6 overflow-y-auto space-y-6 font-mono text-xs">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-800 pb-3">
        <div>
          <h2 className="text-base font-bold text-slate-100 flex items-center gap-2">
            <Plug className="w-4 h-4 text-indigo-400" />
            Connector Governance & Ingestion Dashboard
          </h2>
          <p className="text-slate-500 text-xs">
            Multi-protocol banking connectors, envelope credential vaults, and circuit breaker health
          </p>
        </div>
        <button
          onClick={onRefresh}
          disabled={loading}
          className="px-3 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 flex items-center gap-1.5 transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          <span>Refresh</span>
        </button>
      </div>

      {/* Provider Governance Cards */}
      <div className="space-y-3">
        <h3 className="text-xs font-bold text-slate-300 uppercase tracking-wider flex items-center gap-2">
          <Radio className="w-3.5 h-3.5 text-indigo-400" />
          Registered Providers ({providers.length})
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
          {providers.map((p) => {
            const cred = credentials.find((c) => c.provider_id === p.provider_id);
            const isTriggering = triggeringProvider === p.provider_id;
            return (
              <div
                key={p.provider_id}
                className="p-4 rounded bg-slate-800/60 border border-slate-700/60 flex flex-col justify-between space-y-3 hover:border-slate-600 transition-colors"
              >
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="px-1.5 py-0.5 rounded bg-indigo-950 text-indigo-300 border border-indigo-800 font-bold text-[10px]">
                      {p.protocol_type}
                    </span>
                    {getBreakerBadge(p.circuit_breaker_state)}
                  </div>
                  <div>
                    <h4 className="font-bold text-sm text-slate-100">{p.name}</h4>
                    <p className="text-[11px] text-slate-500 truncate">{p.base_url}</p>
                  </div>
                  <div className="pt-1 border-t border-slate-700/60 grid grid-cols-2 gap-2 text-[10px] text-slate-400">
                    <div>Rate Limit: <span className="text-slate-200 font-bold">{p.rate_limit_rpm} RPM</span></div>
                    <div>Burst: <span className="text-slate-200 font-bold">{p.burst_capacity} req</span></div>
                  </div>
                </div>

                <div className="pt-2 border-t border-slate-700/60 flex items-center justify-between">
                  <div className="flex items-center gap-1.5 text-[10px]">
                    <Key className="w-3 h-3 text-slate-400" />
                    {cred?.has_credentials ? (
                      <span className="text-emerald-400 font-bold">Enveloped</span>
                    ) : (
                      <span className="text-amber-400">No Key</span>
                    )}
                  </div>
                  <button
                    onClick={() => handleTrigger(p.provider_id)}
                    disabled={isTriggering || p.circuit_breaker_state === 'OPEN'}
                    className="px-2.5 py-1 rounded bg-indigo-600 hover:bg-indigo-500 text-white font-sans text-[11px] flex items-center gap-1 shadow-sm transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
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
      <div className="space-y-3">
        <h3 className="text-xs font-bold text-slate-300 uppercase tracking-wider flex items-center gap-2">
          <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
          Envelope Encryption Vault Status
        </h3>
        <div className="border border-slate-800 rounded bg-slate-900/60 divide-y divide-slate-800/60 p-2">
          {credentials.map((c) => (
            <div key={c.provider_id} className="py-2.5 px-2 flex items-center justify-between hover:bg-slate-800/40 rounded transition-colors">
              <div className="flex items-center gap-3">
                <span className="font-bold text-slate-200">{c.provider_id}</span>
                <span className="text-slate-500 text-[11px]">
                  KEK: <span className="text-indigo-300 font-mono">{c.kek_key_id || 'None'}</span>
                </span>
                <span className="text-slate-500 text-[11px]">
                  DEK Age: <span className="text-slate-300 font-bold">{c.dek_rotation_age_days}d</span>
                </span>
              </div>
              <div>{getFreshnessBadge(c.iv_freshness_status)}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Sync Execution Timeline */}
      <div className="space-y-3">
        <h3 className="text-xs font-bold text-slate-300 uppercase tracking-wider flex items-center gap-2">
          <Activity className="w-3.5 h-3.5 text-indigo-400" />
          Sync Execution Timeline
        </h3>
        <div className="border border-slate-800 rounded bg-slate-900/60 p-3 space-y-2">
          {timeline.length === 0 ? (
            <div className="text-center text-slate-500 py-3">No sync events recorded in the active timeline.</div>
          ) : (
            timeline.map((ev) => (
              <div key={ev.event_id} className="flex items-start gap-3 text-xs py-1.5 border-b border-slate-800/40 last:border-0">
                <Clock className="w-3.5 h-3.5 text-indigo-400 shrink-0 mt-0.5" />
                <div className="flex-1 flex items-center justify-between">
                  <div>
                    <span className="font-bold text-slate-200 mr-2">{ev.provider_id}</span>
                    <span className="text-slate-400">{ev.summary}</span>
                  </div>
                  <span className="text-[10px] text-slate-500 font-mono">{ev.timestamp_utc}</span>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Recent Sync Runs Table */}
      <div className="space-y-3">
        <h3 className="text-xs font-bold text-slate-300 uppercase tracking-wider flex items-center gap-2">
          <Clock className="w-3.5 h-3.5 text-slate-400" />
          Recent Ingestion Runs ({syncRuns.length})
        </h3>
        <div className="border border-slate-800 rounded bg-slate-900/60 overflow-hidden">
          <table className="w-full text-left divide-y divide-slate-800/60">
            <thead className="bg-slate-800/40 text-[10px] text-slate-400 uppercase">
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
            <tbody className="divide-y divide-slate-800/40 text-[11px]">
              {syncRuns.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-3 py-4 text-center text-slate-500">
                    No synchronization runs recorded.
                  </td>
                </tr>
              ) : (
                syncRuns.map((r) => (
                  <tr key={r.run_id} className="hover:bg-slate-800/30 transition-colors">
                    <td className="px-3 py-2 font-mono text-slate-300">{r.run_id.slice(0, 10)}</td>
                    <td className="px-3 py-2 font-bold text-slate-200">{r.provider_id}</td>
                    <td className="px-3 py-2">
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                          r.status === 'SUCCESS'
                            ? 'bg-emerald-950 text-emerald-400'
                            : r.status === 'RUNNING'
                            ? 'bg-indigo-950 text-indigo-400 animate-pulse'
                            : 'bg-rose-950 text-rose-400'
                        }`}
                      >
                        {r.status}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-slate-300">{r.records_fetched}</td>
                    <td className="px-3 py-2 text-slate-300 font-bold">{r.records_staged}</td>
                    <td className="px-3 py-2 text-slate-500 font-mono text-[10px]">{r.started_at_utc}</td>
                    <td className="px-3 py-2 text-rose-400 truncate max-w-xs">{r.error_code || '—'}</td>
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
