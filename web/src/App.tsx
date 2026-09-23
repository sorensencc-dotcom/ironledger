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
import { WatchlistPanel } from './components/portfolio/WatchlistPanel';
import { CapitalGainsLedger } from './components/CapitalGainsLedger';
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
  WatchlistData,
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
  const [scanningRules, setScanningRules] = useState(false);

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
  const [watchlistData, setWatchlistData] = useState<WatchlistData | null>(null);
  const [loadingWatchlist, setLoadingWatchlist] = useState(false);
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
      const [stg, proposals, rls, sm, fresh, sync, h, r, dlq] = await Promise.all([
        api.getStaging(statusFilter).catch(() => []),
        api.getAttachProposals().catch(() => []),
        api.getRules().catch(() => []),
        api.getSafeMode().catch(() => null),
        api.getFreshness().catch(() => null),
        api.getSyncStatus().catch(() => null),
        api.getHealthz().catch(() => null),
        api.getReadyz().catch(() => null),
        api.getWebhookDLQ().catch(() => []),
      ]);
      const mappedProposals: StagedTransaction[] = proposals.map((p) => ({
        staged_id: p.proposal_id,
        source_document_id: p.source_document_id,
        source_record_id: p.source_record_id,
        date: p.date,
        payee: p.pdf_description,
        narration: p.kind === 'near_miss' ? 'near-miss suggestion' : 'attach proposal',
        currency: p.currency,
        minor_units: p.minor_units,
        scale: p.scale,
        postings: [],
        status: 'pending',
        confidence_score: null,
        matched_rule_id: null,
        notes: null,
        item_type: 'attach',
        proposal_id: p.proposal_id,
        attach_kind: p.kind,
        candidates: p.candidates,
        pdf_description: p.pdf_description,
      }));
      setStaging([...mappedProposals, ...stg]);
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

  const fetchWatchlist = async () => {
    setLoadingWatchlist(true);
    try {
      const data = await api.getWatchlistData();
      setWatchlistData(data);
    } catch (err) {
      console.error('Failed to load watchlist data:', err);
    } finally {
      setLoadingWatchlist(false);
    }
  };

  const handlePriceSync = async () => {
    try {
      const res = await api.triggerPriceSync();
      await Promise.all([
        fetchWatchlist(),
        api.getPortfolioData().then(setPortfolioHoldings).catch(console.error),
      ]);
      showNotification(`Price sync completed: ${res.synced_count} synced, ${res.failed_count} failed`);
    } catch (err: any) {
      showNotification(err.message || 'Price sync failed', 'error');
    }
  };

  const handleAddWatchlistSymbol = async (symbol: string, quoteCurrency: string, manualQuote?: string) => {
    try {
      await api.addWatchlistSymbol(symbol, quoteCurrency, manualQuote);
      showNotification(`Added ${symbol}/${quoteCurrency} to watchlist`);
      await handlePriceSync();
    } catch (err: any) {
      showNotification(err.message || 'Failed to add symbol', 'error');
      throw err;
    }
  };

  const handleRemoveWatchlistSymbol = async (symbol: string, quoteCurrency: string) => {
    try {
      await api.removeWatchlistSymbol(symbol, quoteCurrency);
      showNotification(`Removed ${symbol}/${quoteCurrency} from watchlist`);
      await Promise.all([
        fetchWatchlist(),
        api.getPortfolioData().then(setPortfolioHoldings).catch(console.error),
      ]);
    } catch (err: any) {
      showNotification(err.message || 'Failed to remove symbol', 'error');
      throw err;
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
        const [p, w] = await Promise.all([
          api.getPortfolioData().catch(() => []),
          api.getWatchlistData().catch(() => null),
        ]);
        setPortfolioHoldings(p);
        setWatchlistData(w);
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
    const item = staging.find((tx) => tx.staged_id === stagedId);
    if (item?.item_type === 'attach') {
      return;
    }
    try {
      await api.approve(stagedId);
      showNotification(`Transaction ${stagedId.slice(0, 8)} approved`);
      refreshAll();
    } catch (err: any) {
      showNotification(err.message, 'error');
    }
  };

  const handleConfirmAttach = async (proposalId: string, chosenStagedId: string) => {
    try {
      await api.confirmAttach(proposalId, chosenStagedId);
      showNotification(`Attached ${proposalId.slice(0, 12)}`);
      refreshAll();
    } catch (err: any) {
      showNotification(err.message, 'error');
    }
  };

  const handleReject = async (stagedId: string) => {
    const item = staging.find((tx) => tx.staged_id === stagedId);
    if (item?.item_type === 'attach' && item.proposal_id) {
      try {
        await api.rejectAttach(item.proposal_id);
        showNotification(`Rejected attach ${item.proposal_id.slice(0, 12)}`);
        refreshAll();
      } catch (err: any) {
        showNotification(err.message, 'error');
      }
      return;
    }
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

  const handleScanRules = async () => {
    setScanningRules(true);
    try {
      const res = await api.autoMatch();
      showNotification(`Scan categorized ${res.matched} of ${res.candidates} rows`);
      refreshAll();
    } catch (err: any) {
      showNotification(err.message, 'error');
    } finally {
      setScanningRules(false);
    }
  };

  const handleCategorize = async (stagedId: string, targetAccount: string) => {
    try {
      await api.categorize(stagedId, targetAccount);
      showNotification(`Categorized ${stagedId.slice(0, 8)} as ${targetAccount}`);
      refreshAll();
    } catch (err: any) {
      showNotification(err.message, 'error');
    }
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
    <div className="h-screen w-screen flex flex-col bg-[#0d0a08] text-[#f2ece2] overflow-hidden font-sans">
      {/* Top HUD */}
      <TopHUD
        activeView={activeView}
        onSelectView={setActiveView}
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
              onScanRules={handleScanRules}
              scanningRules={scanningRules}
            />
            <InspectorSidecar
              transaction={activeTx}
              rules={rules}
              onOpenRuleWizard={handleOpenRuleWizard}
              onCategorize={handleCategorize}
              onConfirmAttach={handleConfirmAttach}
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
          <div className="flex-1 p-6 overflow-y-auto bg-[#0d0a08]">
            <FederationView
              onNotify={(msg, type) => setNotification({ msg, type: type === 'error' ? 'error' : 'success' })}
            />
          </div>
        )}

        {activeView === 'failover' && (
          <div className="flex-1 p-6 overflow-y-auto bg-[#0d0a08]">
            <FailoverView
              onNotify={(msg, type) => setNotification({ msg, type: type === 'error' ? 'error' : 'success' })}
            />
          </div>
        )}

        {activeView === 'rules' && (
          <div className="flex-1 p-6 overflow-y-auto space-y-4 font-mono bg-[#0d0a08] relative">
            <div className="ghost-watermark text-[6rem] -top-8 -right-4 select-none pointer-events-none">
              RULES
            </div>
            <div className="flex items-center justify-between border-b border-[#2c2420] pb-3 relative z-10">
              <h2 className="text-base font-serif font-bold text-[#f2ece2]">Categorization Rules</h2>
              <span className="text-xs text-[#7a6e65] font-mono">{rules.length} active rules</span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 relative z-10">
              {rules.map((rule) => (
                <div key={rule.rule_id} className="p-3.5 rounded-none bg-[#1a1410] border border-[#2c2420] space-y-2 text-xs">
                  <div className="flex items-center justify-between">
                    <span className="px-1.5 py-0.2 rounded-none bg-[#241c16] text-[#b8922a] border border-[#3a2e26] uppercase font-mono font-bold text-[10px]">
                      {rule.match_type}
                    </span>
                    <span className="text-[#7a6e65] text-[10px]">Priority: {rule.priority}</span>
                  </div>
                  <div className="font-bold text-[#f2ece2]">{rule.pattern}</div>
                  <div className="text-[#c4501a] font-mono">&rarr; {rule.target_account}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {activeView === 'balances' && (
          <div className="flex-1 p-6 overflow-y-auto space-y-4 font-mono bg-[#0d0a08] relative">
            <div className="ghost-watermark text-[6rem] -top-8 -right-4 select-none pointer-events-none">
              BALANCES
            </div>
            <div className="flex items-center justify-between border-b border-[#2c2420] pb-3 relative z-10">
              <h2 className="text-base font-serif font-bold text-[#f2ece2]">Account Balances & Chart</h2>
              <span className="text-xs text-[#7a6e65] font-mono">{balances.length} accounts</span>
            </div>
            <div className="divide-y divide-[#2c2420]/60 text-xs bg-[#1a1410] border border-[#2c2420] rounded-none p-3 relative z-10">
              {balances.map((b) => (
                <div key={b.account} className="py-2.5 flex items-center justify-between hover:bg-[#241c16]/50 transition-colors px-2">
                  <span className="text-[#a89e94]">{b.account}</span>
                  <span className="font-bold text-[#f2ece2] font-mono">
                    {b.formatted_amount} <span className="text-[#7a6e65] text-[10px]">{b.currency}</span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {activeView === 'analytics' && (
          <div className="flex-1 p-6 overflow-y-auto space-y-4 font-mono bg-[#0d0a08] relative">
            <div className="ghost-watermark text-[6rem] -top-8 -right-4 select-none pointer-events-none">
              FLOWS
            </div>
            <div className="flex items-center justify-between border-b border-[#2c2420] pb-3 relative z-10">
              <div>
                <h2 className="text-base font-serif font-bold text-[#f2ece2]">Cash Flow &amp; Sankey Visualizer</h2>
                <p className="text-xs text-[#7a6e65]">Directed cash flows from income roots through operating buffer to expenses and investments</p>
              </div>
              <div className="flex items-center gap-3">
                <label className="text-xs text-[#7a6e65] font-sans font-bold uppercase text-[10px]">Period:</label>
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
                  className="bg-[#0d0a08] border border-[#3a2e26] text-[#f2ece2] text-xs px-2.5 py-1 rounded-none focus:outline-none focus:border-[#c4501a] font-mono"
                />
                <button
                  onClick={() => fetchSankeyForPeriod(sankeyPeriod)}
                  disabled={loadingAnalytics}
                  className="px-2.5 py-1 rounded-none text-xs bg-[#1a1410] hover:bg-[#241c16] text-[#e8dfd1] border border-[#3a2e26] font-mono uppercase tracking-wider transition-colors disabled:opacity-50"
                >
                  {loadingAnalytics ? 'Loading...' : 'Refresh'}
                </button>
              </div>
            </div>

            <div className="flex justify-center p-4 bg-[#1a1410] rounded-none border border-[#2c2420] relative z-10">
              {sankeyFlows.length === 0 ? (
                <div className="py-12 text-center text-xs text-[#7a6e65]">
                  No cash flows recorded for period <span className="font-bold text-[#f2ece2] font-mono">{sankeyPeriod}</span>.
                </div>
              ) : (
                <CashFlowSankey flows={sankeyFlows} width={880} height={420} />
              )}
            </div>
          </div>
        )}

        {activeView === 'gains' && <CapitalGainsLedger />}

        {activeView === 'portfolio' && (
          <div className="flex-1 p-6 overflow-y-auto space-y-6 font-mono bg-[#0d0a08] relative">
            <div className="ghost-watermark text-[6rem] -top-8 -right-4 select-none pointer-events-none">
              PORTFOLIO
            </div>
            <div className="flex items-center justify-between border-b border-[#2c2420] pb-3 relative z-10">
              <div>
                <h2 className="text-base font-serif font-bold text-[#f2ece2]">Multi-Asset Portfolio &amp; Watchlist</h2>
                <p className="text-xs text-[#7a6e65]">Real-time valuation, exact rational quotes &amp; automated feed scraping</p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => {
                    api.getPortfolioData().then(setPortfolioHoldings).catch(console.error);
                    fetchWatchlist();
                  }}
                  className="px-2.5 py-1.5 rounded-none text-xs bg-[#1a1410] hover:bg-[#241c16] text-[#e8dfd1] border border-[#3a2e26] font-mono uppercase tracking-wider transition-colors"
                >
                  Refresh All
                </button>
              </div>
            </div>

            <HoldingsView holdings={portfolioHoldings} />

            <WatchlistPanel
              data={watchlistData}
              loading={loadingWatchlist}
              onSync={handlePriceSync}
              onAddSymbol={handleAddWatchlistSymbol}
              onRemoveSymbol={handleRemoveWatchlistSymbol}
            />
          </div>
        )}

        {activeView === 'audit' && (
          <div className="flex-1 p-6 overflow-y-auto space-y-4 font-mono bg-[#0d0a08] relative">
            <div className="ghost-watermark text-[6rem] -top-8 -right-4 select-none pointer-events-none">
              AUDIT
            </div>
            <div className="flex items-center justify-between border-b border-[#2c2420] pb-3 relative z-10">
              <div>
                <h2 className="text-base font-serif font-bold text-[#f2ece2]">Meta-Ledger & Audit Trail</h2>
                <p className="text-xs text-[#7a6e65]">Append-only cryptographically hash-chained state mutations</p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => {
                    api.getAudit().then(setAuditLog).catch(console.error);
                    api.getMutations().then(setMutations).catch(console.error);
                  }}
                  className="px-2.5 py-1 rounded-none text-xs bg-[#1a1410] hover:bg-[#241c16] text-[#e8dfd1] border border-[#3a2e26] font-mono uppercase tracking-wider transition-colors"
                >
                  Refresh Chain
                </button>
              </div>
            </div>

            {/* Mutation Events List */}
            <div className="space-y-3 relative z-10">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-bold text-[#b8922a] font-sans uppercase tracking-wider">Ledger State Mutations ({mutations.length})</h3>
                <span className="text-[10px] text-[#8fc79e] font-bold font-sans uppercase tracking-wider">SHA-256 Chain Verified</span>
              </div>
              <div className="divide-y divide-[#2c2420]/60 text-xs border border-[#2c2420] rounded-none bg-[#1a1410] p-2">
                {mutations.length === 0 ? (
                  <div className="p-4 text-center text-[#7a6e65] text-xs">No mutation events recorded yet.</div>
                ) : (
                  mutations.map((m) => (
                    <div key={m.mutation_id} className="py-2.5 px-2 flex flex-col space-y-1.5 hover:bg-[#241c16]/50 rounded-none transition-colors">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="px-1.5 py-0.2 rounded-none bg-[#241c16] text-[#b8922a] border border-[#3a2e26] font-bold text-[10px] font-mono">
                            SEQ #{m.seq}
                          </span>
                          <span className="text-[#f2ece2] font-bold uppercase font-mono">{m.action}</span>
                        </div>
                        <span className="text-[#7a6e65] text-[10px] font-mono">{m.ts_utc}</span>
                      </div>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[10px] text-[#7a6e65]">
                        <div>Staged: <span className="text-[#f2ece2] font-bold font-mono">{m.staged_count}</span></div>
                        <div>Applied: <span className="text-[#f2ece2] font-bold font-mono">{m.rules_applied}</span></div>
                        <div>Created: <span className="text-[#f2ece2] font-bold font-mono">{m.rules_created}</span></div>
                        <div>Actor: <span className="text-[#b8922a] font-mono">{m.operator_session}</span></div>
                      </div>
                      <div className="text-[10px] font-mono text-[#7a6e65] flex items-center gap-2 truncate">
                        <span>Hash:</span>
                        <span className="text-[#8fc79e] truncate font-mono">{m.mutation_hash}</span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Audit Log Events List */}
            <div className="space-y-3 pt-4 relative z-10">
              <h3 className="text-xs font-bold text-[#b8922a] font-sans uppercase tracking-wider">Operator Audit Events ({auditLog.length})</h3>
              <div className="divide-y divide-[#2c2420]/60 text-xs border border-[#2c2420] rounded-none bg-[#1a1410] p-2">
                {auditLog.length === 0 ? (
                  <div className="p-4 text-center text-[#7a6e65] text-xs">No audit events recorded yet.</div>
                ) : (
                  auditLog.map((a) => (
                    <div key={`${a.sequence_number}-${a.event_hash}`} className="py-2.5 px-2 flex items-center justify-between hover:bg-[#241c16]/50 rounded-none transition-colors">
                      <div className="space-y-0.5">
                        <div className="text-[#f2ece2] font-semibold flex items-center gap-2">
                          <span>{a.action}</span>
                          <span className="text-[#7a6e65] text-[10px] font-mono">({a.target})</span>
                        </div>
                        <div className="text-[#7a6e65] text-[10px] font-mono">
                          Seq #{a.sequence_number} &bull; {a.timestamp_utc} &bull; Actor: {a.actor}
                        </div>
                      </div>
                      <span className={`px-2 py-0.5 rounded-none text-[10px] uppercase font-bold font-mono ${
                        a.result === 'ok' ? 'bg-[#132a1c] text-[#8fc79e] border border-[#1d442b]' : 'bg-[#2c120e] text-[#e2765f] border border-[#4a1c14]'
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
        <div className={`fixed bottom-6 right-6 px-4 py-2.5 rounded-none shadow-2xl font-mono text-xs z-50 flex items-center gap-2 border ${
          notification.type === 'success'
            ? 'bg-[#132a1c]/95 text-[#8fc79e] border-[#1d442b]'
            : 'bg-[#2c120e]/95 text-[#e2765f] border-[#4a1c14]'
        }`}>
          <span>{notification.msg}</span>
        </div>
      )}

      {/* Modals */}
      <RuleWizardModal
        isOpen={isRuleWizardOpen}
        onClose={() => setIsRuleWizardOpen(false)}
        transaction={ruleWizardTx}
        rules={rules}
        onRuleCreated={(matched) => {
          showNotification(`Rule saved, ${matched} rows categorized`);
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
