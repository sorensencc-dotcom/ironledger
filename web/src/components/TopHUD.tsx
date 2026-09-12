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
  Key,
  Server,
} from 'lucide-react';
import type { FreshnessStatus, HealthStatus, SafeModeStatus, SyncStatus } from '../types';
import type { ActiveView } from './Sidebar';

interface TopHUDProps {
  activeView: ActiveView;
  onSelectView: (view: ActiveView) => void;
  safeMode: SafeModeStatus | null;
  freshness: FreshnessStatus | null;
  syncStatus: SyncStatus | null;
  health: HealthStatus | null;
  readiness: HealthStatus | null;
  onOpenSimulation: () => void;
  onOpenCommandPalette: () => void;
  onTriggerCompile: () => void;
  onTriggerSync: () => void;
  isCompiling: boolean;
  isSyncing: boolean;
}

export const TopHUD: React.FC<TopHUDProps> = ({
  activeView,
  onSelectView,
  safeMode,
  freshness,
  syncStatus,
  health,
  readiness,
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
  let freshnessColor = 'bg-loss-tint text-loss-bright border-loss/40 animate-pulse';
  let freshnessDot = 'bg-loss-bright';
  let freshnessLabel = latency >= 999 ? 'PROJECTION: DESYNC' : `PROJECTION: ${latency.toFixed(1)}s`;

  if (latency < 5) {
    freshnessColor = 'bg-gain-tint text-gain-bright border-gain/40';
    freshnessDot = 'bg-gain-bright';
    freshnessLabel = `PROJECTION: ${latency.toFixed(1)}s`;
  } else if (latency <= 30) {
    freshnessColor = 'bg-brass/10 text-brass border-brass/40';
    freshnessDot = 'bg-brass';
    freshnessLabel = `PROJECTION: STALE (${latency.toFixed(1)}s)`;
  }

  // SimpleFIN Aggregator Ingestion Status Indicator
  const syncState = syncStatus?.state ?? 'UNCONFIGURED';
  let syncColor = 'bg-brass/10 text-brass border-brass/40';
  let syncDot = 'bg-brass';
  let syncLabel = 'SIMPLEFIN: OFF';
  let syncTooltip = 'No SimpleFIN credentials stored. Run: ironledger sync auth claim';

  if (syncState === 'HEALTHY') {
    syncColor = 'bg-gain-tint text-gain-bright border-gain/40';
    syncDot = 'bg-gain-bright';
    syncLabel = 'SIMPLEFIN: OK';
    syncTooltip = `SimpleFIN Bridge Connected | Pending in DB: ${syncStatus?.pending_count ?? 0}`;
  } else if (syncState === 'DEGRADED') {
    syncColor = 'bg-loss-tint text-loss-bright border-loss/40 animate-pulse';
    syncDot = 'bg-loss-bright';
    syncLabel = 'SIMPLEFIN: ERR';
    syncTooltip = syncStatus?.last_error_code
      ? `SimpleFIN Degraded: ${syncStatus.last_error_code}`
      : 'SimpleFIN connection error or SSRF warning detected';
  }

  // Probe Status
  const isHealthy = health?.status === 'ok';
  const isReady = readiness?.status === 'ready';

  return (
    <header className="h-14 border-b border-[rgba(139,58,26,0.25)] bg-[#1a1410] px-4 flex items-center justify-between z-20 shrink-0 select-none gap-3 shadow-md">
      {/* Brand & Primary Navigation */}
      <div className="flex items-center space-x-3 shrink-0">
        <div className="flex items-center space-x-2">
          <h1 className="font-display font-black italic text-lg tracking-wide text-brass flex items-center gap-2 whitespace-nowrap">
            IronLedger
            <span className="text-[10px] px-1.5 py-0.5 bg-black/40 text-ash border border-border font-ui font-semibold tracking-widest uppercase not-italic">
              v0.11.0
            </span>
          </h1>
        </div>

        {/* Quick View Navigation Tabs */}
        <nav className="flex items-center bg-black/40 p-0.5 border border-border text-xs font-ui tracking-wider uppercase">
          <button
            onClick={() => onSelectView('staging')}
            className={`px-3 py-1 transition-colors ${
              activeView === 'staging'
                ? 'bg-forge text-white border-b-2 border-ember font-bold'
                : 'text-ash hover:text-bone hover:bg-card-hover'
            }`}
          >
            Staging
          </button>
          <button
            onClick={() => onSelectView('portfolio')}
            className={`px-3 py-1 transition-colors ${
              activeView === 'portfolio'
                ? 'bg-forge text-white border-b-2 border-ember font-bold'
                : 'text-ash hover:text-bone hover:bg-card-hover'
            }`}
          >
            Holdings &amp; Watchlist
          </button>
          <button
            onClick={() => onSelectView('analytics')}
            className={`px-3 py-1 transition-colors ${
              activeView === 'analytics'
                ? 'bg-forge text-white border-b-2 border-ember font-bold'
                : 'text-ash hover:text-bone hover:bg-card-hover'
            }`}
          >
            Cash Flow
          </button>
        </nav>
      </div>

      {/* Center Status HUDs */}
      <div className="flex-1 min-w-0 flex items-center justify-center gap-2 font-ui text-[11px] tracking-wider uppercase overflow-x-auto py-1 px-1 scrollbar-none">
        {/* Health & Readiness Probes (Compact on large, hidden on small) */}
        <div
          className={`px-2 py-1 border hidden lg:inline-flex items-center gap-1.5 whitespace-nowrap shrink-0 ${
            isHealthy && isReady
              ? 'bg-gain-tint text-gain-bright border-gain/40'
              : 'bg-loss-tint text-loss-bright border-loss/40 animate-pulse'
          }`}
          title={`Healthz: ${health?.status || 'unknown'} | Readyz: ${readiness?.status || 'unknown'}`}
        >
          <Server className="w-3.5 h-3.5 text-gain-bright shrink-0" />
          <span>{isHealthy && isReady ? 'PROBES: OK' : 'PROBES: DEGRADED'}</span>
        </div>

        {/* Envelope Encryption HUD */}
        <div
          className="px-2 py-1 border border-border bg-black/40 text-bone hidden xl:inline-flex items-center gap-1.5 whitespace-nowrap shrink-0"
          title="Envelope encryption: AES-256-GCM DEKs wrapped with local KEK"
        >
          <Key className="w-3.5 h-3.5 text-brass shrink-0" />
          <span>ENVELOPE: ACTIVE</span>
        </div>

        {/* Safe Mode Guard Banner */}
        <div
          className={`px-2.5 py-1 border inline-flex items-center gap-1.5 transition-colors whitespace-nowrap shrink-0 ${
            isSafe
              ? 'bg-[rgba(196,80,26,0.1)] text-ember border-[rgba(196,80,26,0.4)]'
              : 'bg-gain-tint text-gain-bright border-gain/40'
          }`}
          title={isSafe ? 'Safe Mode Active: Live compiles require confirmation token' : 'Safe Mode Unlocked: Operator full live write access'}
        >
          {isSafe ? <ShieldAlert className="w-3.5 h-3.5 text-ember shrink-0" /> : <ShieldCheck className="w-3.5 h-3.5 text-gain-bright shrink-0" />}
          <span className="font-bold">{isSafe ? 'SAFE MODE' : 'UNLOCKED'}</span>
        </div>

        {/* SimpleFIN Aggregator Ingestion Status Pill */}
        <div
          className={`px-2.5 py-1 border inline-flex items-center gap-1.5 transition-colors whitespace-nowrap shrink-0 ${syncColor}`}
          title={syncTooltip}
        >
          <span className={`w-1.5 h-1.5 shrink-0 ${syncDot}`} />
          {syncState === 'DEGRADED' ? (
            <AlertTriangle className="w-3.5 h-3.5 text-loss-bright shrink-0" />
          ) : (
            <Landmark className="w-3.5 h-3.5 text-gain-bright shrink-0" />
          )}
          <span>{syncLabel}</span>
        </div>

        {/* Projection Freshness Pill */}
        <div className={`px-2.5 py-1 border inline-flex items-center gap-1.5 transition-colors whitespace-nowrap shrink-0 ${freshnessColor}`}>
          <span className={`w-1.5 h-1.5 shrink-0 ${freshnessDot}`} />
          <RefreshCw className={`w-3.5 h-3.5 shrink-0 ${latency > 5 ? 'animate-spin' : ''}`} />
          <span>{freshnessLabel}</span>
        </div>

        {/* Session Token HUD */}
        <div className="px-2.5 py-1 border border-border bg-black/30 text-ash hidden 2xl:inline-flex items-center gap-1.5 whitespace-nowrap shrink-0 font-mono text-[10px]">
          <Cpu className="w-3.5 h-3.5 text-rust shrink-0" />
          <span>D-0 LOCALHOST</span>
        </div>
      </div>

      {/* Action Controls */}
      <div className="flex items-center space-x-2 shrink-0 font-ui text-xs tracking-wider uppercase font-bold">
        <a
          href="/docs/index.html"
          target="_blank"
          rel="noreferrer"
          className="px-2.5 py-1 bg-black/40 hover:bg-card-hover text-ash hover:text-white border border-border hidden sm:inline-flex items-center gap-1.5 transition-colors whitespace-nowrap"
          title="User Guide & Documentation"
        >
          <HelpCircle className="w-3.5 h-3.5 text-brass" />
          <span>Docs</span>
        </a>

        <button
          onClick={onOpenCommandPalette}
          className="px-2.5 py-1 bg-black/40 hover:bg-card-hover text-ash hover:text-white border border-border hidden md:inline-flex items-center gap-1.5 transition-colors whitespace-nowrap font-mono text-[11px]"
          title="Command Palette (Ctrl+K)"
        >
          <Terminal className="w-3.5 h-3.5 text-ash" />
          <span>Ctrl+K</span>
        </button>

        <button
          onClick={onTriggerSync}
          disabled={isSyncing}
          className="px-3 py-1 bg-black/40 hover:bg-gain-tint text-gain-bright border border-gain/40 inline-flex items-center gap-1.5 transition-colors disabled:opacity-50 whitespace-nowrap"
          title="Poll SimpleFIN Bank Feeds (/api/sync/poll)"
        >
          <Landmark className={`w-3.5 h-3.5 text-gain-bright ${isSyncing ? 'animate-spin' : ''}`} />
          <span>{isSyncing ? 'Syncing...' : 'Bank Sync'}</span>
        </button>

        <button
          onClick={onOpenSimulation}
          className="px-3 py-1 bg-black/40 hover:bg-brass/10 text-brass border border-brass/40 inline-flex items-center gap-1.5 transition-colors whitespace-nowrap"
        >
          <Play className="w-3.5 h-3.5 text-brass" />
          <span>Simulate</span>
        </button>

        <button
          onClick={onTriggerCompile}
          disabled={isCompiling}
          className="px-4 py-1 bg-ember hover:bg-ember/90 text-black font-extrabold inline-flex items-center gap-1.5 shadow-sm transition-colors disabled:opacity-50 whitespace-nowrap"
        >
          {isCompiling ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : null}
          <span>Compile</span>
        </button>
      </div>
    </header>
  );
};
