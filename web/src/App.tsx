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
  Rule,
  SafeModeStatus,
  StagedTransaction,
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

  const [safeMode, setSafeMode] = useState<SafeModeStatus | null>(null);
  const [freshness, setFreshness] = useState<FreshnessStatus | null>(null);

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
      const [stg, rls, sm, fresh] = await Promise.all([
        api.getStaging(statusFilter),
        api.getRules(),
        api.getSafeMode(),
        api.getFreshness(),
      ]);
      setStaging(stg);
      setRules(rls);
      setSafeMode(sm);
      setFreshness(fresh);
    } catch (err) {
      console.error('Failed to load initial workbench data:', err);
    }
  };

  useEffect(() => {
    refreshAll();
    const interval = setInterval(async () => {
      try {
        const fresh = await api.getFreshness();
        setFreshness(fresh);
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
        onOpenSimulation={handleRunSimulation}
        onOpenCommandPalette={() => setIsCommandPaletteOpen(true)}
        onTriggerCompile={handleTriggerCompile}
        isCompiling={compiling}
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
              <h2 className="text-base font-bold text-slate-100">Meta-Ledger Audit Trail</h2>
              <span className="text-xs text-slate-500">{auditLog.length} events</span>
            </div>
            <div className="divide-y divide-slate-800/60 text-xs">
              {auditLog.map((a) => (
                <div key={a.event_id} className="py-2.5 flex items-center justify-between">
                  <div className="space-y-0.5">
                    <div className="text-slate-200 font-semibold">{a.action}</div>
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
              ))}
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

