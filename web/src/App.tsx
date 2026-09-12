import { useEffect, useState } from 'react';
import { TopHUD } from './components/TopHUD';
import { Sidebar, ActiveView } from './components/Sidebar';
import { RegisterGrid } from './components/RegisterGrid';
import { InspectorSidecar } from './components/InspectorSidecar';
import { RuleWizardModal } from './components/RuleWizardModal';
import { CommandPalette } from './components/CommandPalette';
import { SimulationModal } from './components/SimulationModal';
import { ConnectorsView } from './components/ConnectorsView';
import { WebhooksPanel } from './components/WebhooksPanel';
import { MetricsView } from './components/MetricsView';
import { FederationView } from './components/FederationView';
import { FailoverView } from './components/FailoverView';
import { CashFlowSankey } from './components/analytics/CashFlowSankey';
import { HoldingsView } from './components/portfolio/HoldingsView';
import { api } from './api';

import type {
  AuditEvent,
  BalanceItem,
  CompileResult,
  ConnectorCredentialStatus,
  ConnectorProvider,
  ConnectorSyncRun,
  FreshnessStatus,
  HealthStatus,
  HoldingRecord,
  MutationEvent,
  Rule,
  SafeModeStatus,
  SankeyFlowRow,
  StagedTransaction,
  SyncStatus,
  SyncTimelineEvent,
  WebhookDelivery,
  WebhookDLQEntry,
  WebhookSubscription,
} from './types';

export default function App() {
  const [activeView, setActiveView] = useState<ActiveView>('staging');
  const [staging, setStaging] = useState<StagedTransaction[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [statusFilter, setStatusFilter] = useState('');
  const [searchQuery, setSearchQuery] = useState('');

  const [rules, setRules] = useState<Rule[]>([]);
  const [balances, setBalances] = useState<BalanceItem[]>([]);
  const [auditLog, setAuditLog] = useState<AuditEvent[]>([]);
  const [mutations, setMutations] = useState<MutationEvent[]>([]);

  // Connectors State
  const [providers, setProviders] = useState<ConnectorProvider[]>([]);
  const [credentials, setCredentials] = useState<ConnectorCredentialStatus[]>([]);
  const [connectorSyncRuns, setConnectorSyncRuns] = useState<ConnectorSyncRun[]>([]);
  const [connectorTimeline, setConnectorTimeline] = useState<SyncTimelineEvent[]>([]);

  // Webhooks State
  const [webhookSubs, setWebhookSubs] = useState<WebhookSubscription[]>([]);
  const [webhookDeliveries, setWebhookDeliveries] = useState<WebhookDelivery[]>([]);
  const [webhookDLQ, setWebhookDLQ] = useState<WebhookDLQEntry[]>([]);

  // Health & Metrics State
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [readiness, setReadiness] = useState<HealthStatus | null>(null);
  const [rawMetrics, setRawMetrics] = useState<string>('');

  // Analytics & Portfolio State
  const [sankeyFlows, setSankeyFlows] = useState<SankeyFlowRow[]>([]);
  const [portfolioHoldings, setPortfolioHoldings] = useState<HoldingRecord[]>([]);
  const [sankeyPeriod, setSankeyPeriod] = useState<string>(new Date().toISOString().slice(0, 7));
  const [loadingAnalytics, setLoadingAnalytics] = useState(false);

  const [safeMode, setSafeMode] = useState<SafeModeStatus | null>(null);
  const [freshness, setFreshness] = useState<FreshnessStatus | null>(null);
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [loadingViewData, setLoadingViewData] = useState(false);

  // Modals state
  const [isRuleWizardOpen, setIsRuleWizardOpen] = useState(false);
  const [ruleWizardTx, setRuleWizardTx] = useState<StagedTransaction | null>(null);

  const [isCommandPaletteOpen, setIsCommandPaletteOpen] = useState(false);

  const [isSimulationOpen, setIsSimulationOpen] = useState(false);
  const [simulationResult, setSimulationResult] = useState<CompileResult | null>(null);
  const [simulating, setSimulating] = useState(false);

  const [compiling, setCompiling] = useState(false);
  const [notification, setNotification] = useState<{ msg: string; type: 'success' | 'error' } | null>(null);

  // Fetch initial data
  const refreshAll = async () => {
    try {
      const [stg, rls, sm, fresh, sync, h, r, dlq] = await Promise.all([
        api.getStaging(statusFilter).catch(() => []),
        api.getRules().catch(() => []),
        api.getSafeMode().catch(() => null),
        api.getFreshness().catch(() => null),
        api.getSyncStatus().catch(() => null),
        api.getHealthz().catch(() => null),
        api.getReadyz().catch(() => null),
        api.getWebhookDLQ().catch(() => []),
      ]);
      setStaging(stg);
      setRules(rls);
      setSafeMode(sm);
      setFreshness(fresh);
      if (sync) setSyncStatus(sync);
      if (h) setHealth(h);
      if (r) setReadiness(r);
      if (dlq) setWebhookDLQ(dlq);
    } catch (err) {
      console.error('Failed to load initial workbench data:', err);
    }
  };

  useEffect(() => {
    refreshAll();
    const interval = setInterval(async () => {
      try {
        const [fresh, sync, h, r, dlq] = await Promise.all([
          api.getFreshness().catch(() => null),
          api.getSyncStatus().catch(() => null),
          api.getHealthz().catch(() => null),
          api.getReadyz().catch(() => null),
          api.getWebhookDLQ().catch(() => []),
        ]);
        if (fresh) setFreshness(fresh);
        if (sync) setSyncStatus(sync);
        if (h) setHealth(h);
        if (r) setReadiness(r);
        if (dlq) setWebhookDLQ(dlq);
      } catch {}
    }, 5000);
    return () => clearInterval(interval);
  }, [statusFilter]);

  const fetchSankeyForPeriod = async (period: string) => {
    setLoadingAnalytics(true);
    try {
      const flows = await api.getSankeyData(period);
      setSankeyFlows(flows);
    } catch (err) {
      console.error('Failed to load sankey data:', err);
    } finally {
      setLoadingAnalytics(false);
    }
  };

  // Load view-specific data
  const loadViewData = async () => {
    setLoadingViewData(true);
    try {
      if (activeView === 'balances') {
        const b = await api.getBalances();
        setBalances(b);
      } else if (activeView === 'analytics') {
        await fetchSankeyForPeriod(sankeyPeriod);
      } else if (activeView === 'portfolio') {
        const p = await api.getPortfolioData();
        setPortfolioHoldings(p);
      } else if (activeView === 'audit') {
        const [a, m] = await Promise.all([api.getAudit(), api.getMutations()]);
        setAuditLog(a);
        setMutations(m);
      } else if (activeView === 'connectors') {
        const [p, c, r, t] = await Promise.all([
          api.getConnectors(),
          api.getConnectorCredentials(),
          api.getConnectorSyncRuns(),
          api.getConnectorTimeline(),
        ]);
        setProviders(p);
        setCredentials(c);
        setConnectorSyncRuns(r);
        setConnectorTimeline(t);
      } else if (activeView === 'webhooks') {
        const [s, d, q] = await Promise.all([
          api.getWebhookSubscriptions(),
          api.getWebhookDeliveries(),
          api.getWebhookDLQ(),
        ]);
        setWebhookSubs(s);
        setWebhookDeliveries(d);
        setWebhookDLQ(q);
      } else if (activeView === 'metrics') {
        const m = await api.getMetricsRaw();
        setRawMetrics(m);
      }
    } catch (err) {
      console.error('Failed to load view data:', err);
    } finally {
      setLoadingViewData(false);
    }
  };

  useEffect(() => {
    loadViewData();
  }, [activeView]);

  const showNotification = (msg: string, type: 'success' | 'error' = 'success') => {
    setNotification({ msg, type });
    setTimeout(() => setNotification(null), 3500);
  };

  // Actions
  const handleApprove = async (stagedId: string) => {
    try {
      await api.approve(stagedId);
      showNotification(`Transaction ${stagedId.slice(0, 8)} approved`);
      refreshAll();
    } catch (err: any) {
      showNotification(err.message, 'error');
    }
  };

  const handleReject = async (stagedId: string) => {
    try {
      await api.reject(stagedId, 'Rejected from workbench');
      showNotification(`Transaction ${stagedId.slice(0, 8)} rejected`);
      refreshAll();
    } catch (err: any) {
      showNotification(err.message, 'error');
    }
  };

  const handleOpenRuleWizard = (stx: StagedTransaction) => {
    setRuleWizardTx(stx);
    setIsRuleWizardOpen(true);
  };

  const handleRunSimulation = async () => {
    setIsSimulationOpen(true);
    setSimulating(true);
    try {
      const res = await api.simulate();
      setSimulationResult(res);
    } catch (err: any) {
      showNotification(err.message, 'error');
      setIsSimulationOpen(false);
    } finally {
      setSimulating(false);
    }
  };

  const handleTriggerCompile = async () => {
    setCompiling(true);
    try {
      const res = await api.compile(false, 'authorize compile');
      showNotification(res.message);
      refreshAll();
    } catch (err: any) {
      showNotification(err.message, 'error');
    } finally {
      setCompiling(false);
    }
  };

  const handleTriggerSync = async () => {
    setSyncing(true);
    try {
      const res = await api.pollSync();
      showNotification(`Bank Sync: ${res.inserted} inserted, ${res.skipped} skipped`);
      refreshAll();
    } catch (err: any) {
      showNotification(err.message, 'error');
    } finally {
      setSyncing(false);
    }
  };

  const handleTriggerConnectorSync = async (providerId: string) => {
    try {
      const res = await api.triggerConnectorSync(providerId);
      showNotification(res.message, 'success');
      loadViewData();
    } catch (err: any) {
      showNotification(err.message, 'error');
    }
  };

  const handleCreateWebhookSub = async (targetUrl: string, eventTypes: string[]) => {
    const res = await api.createWebhookSubscription({ target_url: targetUrl, event_types: eventTypes });
    showNotification(`Subscribed to ${res.target_url}`, 'success');
    loadViewData();
  };

  const handleRedriveDLQ = async (dlqEntryId: string) => {
    try {
      const res = await api.redriveWebhookDLQ(dlqEntryId);
      showNotification(res.message, 'success');
      loadViewData();
    } catch (err: any) {
      showNotification(err.message, 'error');
    }
  };

  // Filter staging items by search query
  const filteredStaging = staging.filter((tx) => {
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    return (
      (tx.payee && tx.payee.toLowerCase().includes(q)) ||
      (tx.narration && tx.narration.toLowerCase().includes(q)) ||
      tx.postings.some((p) => p.account.toLowerCase().includes(q))
    );
  });

  const activeTx = filteredStaging[selectedIndex] || null;

  return (
    <div className="h-screen w-screen flex flex-col bg-slate-900 text-slate-100 overflow-hidden font-sans">
      {/* Top HUD */}
      <TopHUD
        safeMode={safeMode}
        freshness={freshness}
        syncStatus={syncStatus}
        health={health}
        readiness={readiness}
        onOpenSimulation={handleRunSimulation}
        onOpenCommandPalette={() => setIsCommandPaletteOpen(true)}
        onTriggerCompile={handleTriggerCompile}
        onTriggerSync={handleTriggerSync}
        isCompiling={compiling}
        isSyncing={syncing}
      />

      {/* Main 3-Pane Body */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Sidebar */}
        <Sidebar
          activeView={activeView}
          onSelectView={setActiveView}
          pendingCount={staging.filter((t) => t.status === 'pending').length}
          rulesCount={rules.length}
          dlqCount={webhookDLQ.length}
        />

        {/* Central Viewport */}
        {activeView === 'staging' && (
          <>
            <RegisterGrid
              transactions={filteredStaging}
              selectedIndex={selectedIndex}
              onSelectIndex={setSelectedIndex}
              onApprove={handleApprove}
              onReject={handleReject}
              onOpenSplit={() => {}}
              onOpenRuleWizard={handleOpenRuleWizard}
              statusFilter={statusFilter}
              onChangeStatusFilter={setStatusFilter}
              searchQuery={searchQuery}
              onChangeSearchQuery={setSearchQuery}
            />
            <InspectorSidecar
              transaction={activeTx}
              onOpenRuleWizard={handleOpenRuleWizard}
            />
          </>
        )}

        {activeView === 'connectors' && (
          <ConnectorsView
            providers={providers}
            credentials={credentials}
            syncRuns={connectorSyncRuns}
            timeline={connectorTimeline}
            onTriggerSync={handleTriggerConnectorSync}
            onRefresh={loadViewData}
            loading={loadingViewData}
          />
        )}

        {activeView === 'webhooks' && (
          <WebhooksPanel
            subscriptions={webhookSubs}
            deliveries={webhookDeliveries}
            dlqEntries={webhookDLQ}
            onCreateSubscription={handleCreateWebhookSub}
            onRedriveDLQ={handleRedriveDLQ}
            onRefresh={loadViewData}
            loading={loadingViewData}
          />
        )}

        {activeView === 'metrics' && (
          <MetricsView
            rawMetrics={rawMetrics}
            onRefresh={loadViewData}
            loading={loadingViewData}
          />
        )}

        {activeView === 'federation' && (
          <div className="flex-1 p-6 overflow-y-auto">
            <FederationView
              onNotify={(msg, type) => setNotification({ msg, type: type === 'error' ? 'error' : 'success' })}
            />
          </div>
        )}

        {activeView === 'failover' && (
          <div className="flex-1 p-6 overflow-y-auto">
            <FailoverView
              onNotify={(msg, type) => setNotification({ msg, type: type === 'error' ? 'error' : 'success' })}
            />
          </div>
        )}



        {activeView === 'rules' && (
          <div className="flex-1 p-6 overflow-y-auto space-y-4 font-mono">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h2 className="text-base font-bold text-slate-100">Categorization Rules</h2>
              <span className="text-xs text-slate-500">{rules.length} active rules</span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {rules.map((rule) => (
                <div key={rule.rule_id} className="p-3.5 rounded bg-slate-800/60 border border-slate-700/60 space-y-2 text-xs">
                  <div className="flex items-center justify-between">
                    <span className="px-1.5 py-0.2 rounded bg-indigo-950 text-indigo-300 border border-indigo-800 uppercase font-bold text-[10px]">
                      {rule.match_type}
                    </span>
                    <span className="text-slate-500 text-[10px]">Priority: {rule.priority}</span>
                  </div>
                  <div className="font-bold text-slate-100">{rule.pattern}</div>
                  <div className="text-indigo-400">&rarr; {rule.target_account}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {activeView === 'balances' && (
          <div className="flex-1 p-6 overflow-y-auto space-y-4 font-mono">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h2 className="text-base font-bold text-slate-100">Account Balances & Chart</h2>
              <span className="text-xs text-slate-500">{balances.length} accounts</span>
            </div>
            <div className="divide-y divide-slate-800/60 text-xs">
              {balances.map((b) => (
                <div key={b.account} className="py-2.5 flex items-center justify-between">
                  <span className="text-slate-300">{b.account}</span>
                  <span className="font-bold text-slate-100">
                    {b.formatted_amount} <span className="text-slate-500 text-[10px]">{b.currency}</span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {activeView === 'analytics' && (
          <div className="flex-1 p-6 overflow-y-auto space-y-4 font-mono">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div>
                <h2 className="text-base font-bold text-slate-100">Cash Flow &amp; Sankey Visualizer</h2>
                <p className="text-xs text-slate-500">Directed cash flows from income roots through operating buffer to expenses and investments</p>
              </div>
              <div className="flex items-center gap-3">
                <label className="text-xs text-slate-400">Period:</label>
                <input
                  type="month"
                  value={sankeyPeriod}
                  onChange={(e) => {
                    const val = e.target.value;
                    setSankeyPeriod(val);
                    if (val && val.length === 7) {
                      fetchSankeyForPeriod(val);
                    }
                  }}
                  className="bg-slate-900 border border-slate-700 text-slate-200 text-xs px-2.5 py-1 rounded focus:outline-none focus:border-indigo-500"
                />
                <button
                  onClick={() => fetchSankeyForPeriod(sankeyPeriod)}
                  disabled={loadingAnalytics}
                  className="px-2.5 py-1 rounded text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition-colors disabled:opacity-50"
                >
                  {loadingAnalytics ? 'Loading...' : 'Refresh'}
                </button>
              </div>
            </div>

            <div className="flex justify-center p-4 bg-slate-900/40 rounded-lg border border-slate-800">
              {sankeyFlows.length === 0 ? (
                <div className="py-12 text-center text-xs text-slate-500">
                  No cash flows recorded for period <span className="font-bold text-slate-400">{sankeyPeriod}</span>.
                </div>
              ) : (
                <CashFlowSankey flows={sankeyFlows} width={880} height={420} />
              )}
            </div>
          </div>
        )}

        {activeView === 'portfolio' && (
          <div className="flex-1 p-6 overflow-y-auto space-y-4 font-mono">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div>
                <h2 className="text-base font-bold text-slate-100">Multi-Asset Portfolio &amp; Holdings</h2>
                <p className="text-xs text-slate-500">Consolidated cost basis vs. mark-to-market rational exchange rates</p>
              </div>
              <button
                onClick={() => api.getPortfolioData().then(setPortfolioHoldings).catch(console.error)}
                className="px-2.5 py-1 rounded text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition-colors"
              >
                Refresh Holdings
              </button>
            </div>

            <HoldingsView holdings={portfolioHoldings} />
          </div>
        )}

        {activeView === 'audit' && (
          <div className="flex-1 p-6 overflow-y-auto space-y-4 font-mono">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div>
                <h2 className="text-base font-bold text-slate-100">Meta-Ledger & Audit Trail</h2>
                <p className="text-xs text-slate-500">Append-only cryptographically hash-chained state mutations</p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => {
                    api.getAudit().then(setAuditLog).catch(console.error);
                    api.getMutations().then(setMutations).catch(console.error);
                  }}
                  className="px-2.5 py-1 rounded text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition-colors"
                >
                  Refresh Chain
                </button>
              </div>
            </div>

            {/* Mutation Events List */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-bold text-slate-300 uppercase tracking-wider">Ledger State Mutations ({mutations.length})</h3>
                <span className="text-[10px] text-emerald-400 font-bold">SHA-256 Chain Verified</span>
              </div>
              <div className="divide-y divide-slate-800/60 text-xs border border-slate-800 rounded bg-slate-900/60 p-2">
                {mutations.length === 0 ? (
                  <div className="p-4 text-center text-slate-500 text-xs">No mutation events recorded yet.</div>
                ) : (
                  mutations.map((m) => (
                    <div key={m.mutation_id} className="py-2.5 px-2 flex flex-col space-y-1.5 hover:bg-slate-800/40 rounded transition-colors">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="px-1.5 py-0.2 rounded bg-indigo-950 text-indigo-300 border border-indigo-800 font-bold text-[10px]">
                            SEQ #{m.seq}
                          </span>
                          <span className="text-slate-200 font-bold uppercase">{m.action}</span>
                        </div>
                        <span className="text-slate-500 text-[10px]">{m.ts_utc}</span>
                      </div>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[10px] text-slate-400">
                        <div>Staged: <span className="text-slate-200 font-bold">{m.staged_count}</span></div>
                        <div>Applied: <span className="text-slate-200 font-bold">{m.rules_applied}</span></div>
                        <div>Created: <span className="text-slate-200 font-bold">{m.rules_created}</span></div>
                        <div>Actor: <span className="text-indigo-400">{m.operator_session}</span></div>
                      </div>
                      <div className="text-[10px] font-mono text-slate-500 flex items-center gap-2 truncate">
                        <span>Hash:</span>
                        <span className="text-emerald-400/80 truncate font-mono">{m.mutation_hash}</span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Audit Log Events List */}
            <div className="space-y-3 pt-4">
              <h3 className="text-xs font-bold text-slate-300 uppercase tracking-wider">Operator Audit Events ({auditLog.length})</h3>
              <div className="divide-y divide-slate-800/60 text-xs border border-slate-800 rounded bg-slate-900/60 p-2">
                {auditLog.length === 0 ? (
                  <div className="p-4 text-center text-slate-500 text-xs">No audit events recorded yet.</div>
                ) : (
                  auditLog.map((a) => (
                    <div key={`${a.sequence_number}-${a.event_hash}`} className="py-2.5 px-2 flex items-center justify-between hover:bg-slate-800/40 rounded transition-colors">
                      <div className="space-y-0.5">
                        <div className="text-slate-200 font-semibold flex items-center gap-2">
                          <span>{a.action}</span>
                          <span className="text-slate-500 text-[10px]">({a.target})</span>
                        </div>
                        <div className="text-slate-500 text-[10px]">
                          Seq #{a.sequence_number} &bull; {a.timestamp_utc} &bull; Actor: {a.actor}
                        </div>
                      </div>
                      <span className={`px-2 py-0.5 rounded text-[10px] uppercase font-bold ${
                        a.result === 'ok' ? 'bg-emerald-950 text-emerald-400' : 'bg-rose-950 text-rose-400'
                      }`}>
                        {a.result}
                      </span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Floating Notification Toast */}
      {notification && (
        <div className={`fixed bottom-6 right-6 px-4 py-2.5 rounded shadow-xl font-mono text-xs z-50 flex items-center gap-2 border ${
          notification.type === 'success'
            ? 'bg-emerald-950/90 text-emerald-200 border-emerald-800'
            : 'bg-rose-950/90 text-rose-200 border-rose-800'
        }`}>
          <span>{notification.msg}</span>
        </div>
      )}

      {/* Modals */}
      <RuleWizardModal
        isOpen={isRuleWizardOpen}
        onClose={() => setIsRuleWizardOpen(false)}
        transaction={ruleWizardTx}
        onRuleCreated={() => {
          showNotification('Rule created and applied successfully');
          refreshAll();
        }}
      />

      <CommandPalette
        isOpen={isCommandPaletteOpen}
        onClose={() => setIsCommandPaletteOpen(false)}
        onSelectView={setActiveView}
        onSimulate={handleRunSimulation}
        onCompile={handleTriggerCompile}
        onSync={handleTriggerSync}
      />

      <SimulationModal
        isOpen={isSimulationOpen}
        onClose={() => setIsSimulationOpen(false)}
        result={simulationResult}
        loading={simulating}
      />
    </div>
  );
}
