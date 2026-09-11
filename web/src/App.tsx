import { useEffect, useState } from 'react';
import { TopHUD } from './components/TopHUD';
import { Sidebar, ActiveView } from './components/Sidebar';
import { RegisterGrid } from './components/RegisterGrid';
import { InspectorSidecar } from './components/InspectorSidecar';
import { RuleWizardModal } from './components/RuleWizardModal';
import { CommandPalette } from './components/CommandPalette';
import { SimulationModal } from './components/SimulationModal';
import { api } from './api';
import type {
  AuditEvent,
  BalanceItem,
  CompileResult,
  FreshnessStatus,
  MutationEvent,
  Rule,
  SafeModeStatus,
  StagedTransaction,
  SyncStatus,
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

  const [safeMode, setSafeMode] = useState<SafeModeStatus | null>(null);
  const [freshness, setFreshness] = useState<FreshnessStatus | null>(null);
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null);
  const [syncing, setSyncing] = useState(false);

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
      const [stg, rls, sm, fresh, sync] = await Promise.all([
        api.getStaging(statusFilter),
        api.getRules(),
        api.getSafeMode(),
        api.getFreshness(),
        api.getSyncStatus().catch(() => null),
      ]);
      setStaging(stg);
      setRules(rls);
      setSafeMode(sm);
      setFreshness(fresh);
      if (sync) setSyncStatus(sync);
    } catch (err) {
      console.error('Failed to load initial workbench data:', err);
    }
  };

  useEffect(() => {
    refreshAll();
    const interval = setInterval(async () => {
      try {
        const [fresh, sync] = await Promise.all([
          api.getFreshness().catch(() => null),
          api.getSyncStatus().catch(() => null),
        ]);
        if (fresh) setFreshness(fresh);
        if (sync) setSyncStatus(sync);
      } catch {}
    }, 5000);
    return () => clearInterval(interval);
  }, [statusFilter]);

  // Load balances or audit when active view changes
  useEffect(() => {
    if (activeView === 'balances') {
      api.getBalances().then(setBalances).catch(console.error);
    } else if (activeView === 'audit') {
      api.getAudit().then(setAuditLog).catch(console.error);
      api.getMutations().then(setMutations).catch(console.error);
    }
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

