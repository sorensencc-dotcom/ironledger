import React from 'react';
import {
  ShieldAlert,
  ShieldCheck,
  RefreshCw,
  Terminal,
  Play,
  Cpu,
  HelpCircle,
  Landmark,
  AlertTriangle,
} from 'lucide-react';
import type { FreshnessStatus, SafeModeStatus, SyncStatus } from '../types';

interface TopHUDProps {
  safeMode: SafeModeStatus | null;
  freshness: FreshnessStatus | null;
  syncStatus: SyncStatus | null;
  onOpenSimulation: () => void;
  onOpenCommandPalette: () => void;
  onTriggerCompile: () => void;
  onTriggerSync: () => void;
  isCompiling: boolean;
  isSyncing: boolean;
}

export const TopHUD: React.FC<TopHUDProps> = ({
  safeMode,
  freshness,
  syncStatus,
  onOpenSimulation,
  onOpenCommandPalette,
  onTriggerCompile,
  onTriggerSync,
  isCompiling,
  isSyncing,
}) => {
  const isSafe = safeMode?.enabled ?? true;

  // Multi-threshold Freshness Indicator (<5s green, 5-30s amber, >30s rose pulse)
  const latency = freshness?.latency_seconds ?? 999;
  let freshnessColor = 'bg-rose-950/60 text-rose-300 border-rose-700/80 animate-pulse';
  let freshnessDot = 'bg-rose-500 shadow-rose-500/50';
  let freshnessLabel = `Projection: Desync (${latency >= 999 ? 'No sync' : `${latency.toFixed(1)}s`})`;

  if (latency < 5) {
    freshnessColor = 'bg-emerald-950/50 text-emerald-300 border-emerald-700/60';
    freshnessDot = 'bg-emerald-400 shadow-emerald-400/50';
    freshnessLabel = `Projection: Synced (${latency.toFixed(1)}s)`;
  } else if (latency <= 30) {
    freshnessColor = 'bg-amber-950/50 text-amber-300 border-amber-700/60';
    freshnessDot = 'bg-amber-400 shadow-amber-400/50';
    freshnessLabel = `Projection: Stale (${latency.toFixed(1)}s)`;
  }

  // SimpleFIN Aggregator Ingestion Status Indicator
  const syncState = syncStatus?.state ?? 'UNCONFIGURED';
  let syncColor = 'bg-amber-950/50 text-amber-300 border-amber-700/60';
  let syncDot = 'bg-amber-400 shadow-amber-400/50';
  let syncLabel = 'SimpleFIN: Unconfigured';
  let syncTooltip = 'No SimpleFIN credentials stored. Run: ironledger sync auth claim';

  if (syncState === 'HEALTHY') {
    syncColor = 'bg-emerald-950/50 text-emerald-300 border-emerald-700/60';
    syncDot = 'bg-emerald-400 shadow-emerald-400/50';
    syncLabel = 'SimpleFIN: Healthy';
    syncTooltip = `SimpleFIN Bridge Connected | Pending in DB: ${syncStatus?.pending_count ?? 0}`;
  } else if (syncState === 'DEGRADED') {
    syncColor = 'bg-rose-950/60 text-rose-300 border-rose-700/80 animate-pulse';
    syncDot = 'bg-rose-500 shadow-rose-500/50';
    syncLabel = 'SimpleFIN: Degraded';
    syncTooltip = syncStatus?.last_error_code
      ? `SimpleFIN Degraded: ${syncStatus.last_error_code}`
      : 'SimpleFIN connection error or SSRF warning detected';
  }

  return (
    <header className="h-14 border-b border-slate-700 bg-slate-900 px-4 flex items-center justify-between z-20 shrink-0 select-none gap-3">
      {/* Brand */}
      <div className="flex items-center space-x-2.5 shrink-0">
        <div className="flex items-center justify-center w-8 h-8 rounded bg-indigo-600 text-white font-mono font-bold text-sm shadow-md shadow-indigo-500/20">
          IL
        </div>
        <div className="flex items-center gap-2">
          <h1 className="font-semibold text-sm tracking-wide text-slate-100 flex items-center gap-2 whitespace-nowrap">
            IronLedger
            <span className="text-[10px] px-1.5 py-0.2 rounded bg-indigo-950 text-indigo-300 border border-indigo-800/80 font-mono font-normal">
              v0.7.0
            </span>
          </h1>
        </div>
      </div>

      {/* Center Status HUDs */}
      <div className="flex items-center space-x-2.5 font-mono text-xs overflow-x-auto py-1">
        {/* Safe Mode Guard Banner with Explicit Permissions */}
        <div
          className={`px-2.5 py-1 rounded border flex items-center gap-2 transition-colors whitespace-nowrap shrink-0 ${
            isSafe
              ? 'bg-rose-950/50 text-rose-300 border-rose-800/60'
              : 'bg-emerald-950/50 text-emerald-300 border-emerald-800/60'
          }`}
          title={isSafe ? 'Safe Mode Active: Live compiles require confirmation token' : 'Safe Mode Unlocked: Operator full live write access'}
        >
          {isSafe ? <ShieldAlert className="w-3.5 h-3.5 text-rose-400 shrink-0" /> : <ShieldCheck className="w-3.5 h-3.5 text-emerald-400 shrink-0" />}
          <div className="flex items-center gap-1.5">
            <span className="font-bold">{isSafe ? 'SAFE MODE' : 'UNLOCKED'}</span>
            <span className="text-[10px] text-slate-400 hidden 2xl:inline">
              ({isSafe ? 'Simulate: OK | Compile: Token' : 'All Permitted'})
            </span>
          </div>
        </div>

        {/* SimpleFIN Aggregator Ingestion Status Pill */}
        <div
          className={`px-2.5 py-1 rounded border flex items-center gap-2 transition-colors whitespace-nowrap shrink-0 ${syncColor}`}
          title={syncTooltip}
        >
          <span className={`w-2 h-2 rounded-full ${syncDot} shadow-sm`} />
          {syncState === 'DEGRADED' ? (
            <AlertTriangle className="w-3.5 h-3.5 text-rose-400 shrink-0" />
          ) : (
            <Landmark className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
          )}
          <span>{syncLabel}</span>
        </div>

        {/* Projection Freshness Pill */}
        <div className={`px-2.5 py-1 rounded border flex items-center gap-2 transition-colors whitespace-nowrap shrink-0 ${freshnessColor}`}>
          <span className={`w-2 h-2 rounded-full ${freshnessDot} shadow-sm`} />
          <RefreshCw className={`w-3.5 h-3.5 ${latency > 5 ? 'animate-spin' : ''}`} />
          <span>{freshnessLabel}</span>
        </div>

        {/* Session Token HUD */}
        <div className="px-2.5 py-1 rounded border border-slate-700 bg-slate-800/60 text-slate-300 flex items-center gap-1.5 whitespace-nowrap shrink-0">
          <Cpu className="w-3.5 h-3.5 text-indigo-400" />
          <span>D-0 LOCALHOST</span>
        </div>
      </div>

      {/* Action Controls */}
      <div className="flex items-center space-x-2 shrink-0">
        <a
          href="/docs/index.html"
          target="_blank"
          rel="noreferrer"
          className="px-2.5 py-1 rounded text-xs font-mono bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 flex items-center gap-1.5 transition-colors whitespace-nowrap"
          title="User Guide & Documentation"
        >
          <HelpCircle className="w-3.5 h-3.5 text-indigo-400" />
          <span>Docs</span>
        </a>

        <button
          onClick={onOpenCommandPalette}
          className="px-2.5 py-1 rounded text-xs font-mono bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 flex items-center gap-1.5 transition-colors whitespace-nowrap"
          title="Command Palette (Ctrl+K)"
        >
          <Terminal className="w-3.5 h-3.5 text-slate-400" />
          <span>Ctrl+K</span>
        </button>

        <button
          onClick={onTriggerSync}
          disabled={isSyncing}
          className="px-3 py-1 rounded text-xs font-medium bg-slate-800 hover:bg-slate-700 text-emerald-300 border border-emerald-700/50 flex items-center gap-1.5 transition-colors disabled:opacity-50 whitespace-nowrap"
          title="Poll SimpleFIN Bank Feeds (/api/sync/poll)"
        >
          <Landmark className={`w-3.5 h-3.5 text-emerald-400 ${isSyncing ? 'animate-spin' : ''}`} />
          <span>{isSyncing ? 'Syncing...' : 'Bank Sync'}</span>
        </button>

        <button
          onClick={onOpenSimulation}
          className="px-3 py-1 rounded text-xs font-medium bg-slate-800 hover:bg-slate-700 text-indigo-300 border border-indigo-700/50 flex items-center gap-1.5 transition-colors whitespace-nowrap"
        >
          <Play className="w-3.5 h-3.5 text-indigo-400" />
          <span>Simulate</span>
        </button>

        <button
          onClick={onTriggerCompile}
          disabled={isCompiling}
          className="px-3 py-1 rounded text-xs font-medium bg-indigo-600 hover:bg-indigo-500 text-white font-sans flex items-center gap-1.5 shadow-sm transition-colors disabled:opacity-50 whitespace-nowrap"
        >
          {isCompiling ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : null}
          <span>Compile</span>
        </button>
      </div>
    </header>
  );
};

