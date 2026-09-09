import React, { useEffect, useRef } from 'react';
import { Check, X, Split, AlertCircle } from 'lucide-react';
import type { StagedTransaction } from '../types';

interface RegisterGridProps {
  transactions: StagedTransaction[];
  selectedIndex: number;
  onSelectIndex: (index: number) => void;
  onApprove: (stagedId: string) => void;
  onReject: (stagedId: string) => void;
  onOpenSplit: (stx: StagedTransaction) => void;
  onOpenRuleWizard: (stx: StagedTransaction) => void;
  statusFilter: string;
  onChangeStatusFilter: (status: string) => void;
  searchQuery: string;
  onChangeSearchQuery: (query: string) => void;
}

export const RegisterGrid: React.FC<RegisterGridProps> = ({
  transactions,
  selectedIndex,
  onSelectIndex,
  onApprove,
  onReject,
  onOpenSplit,
  onOpenRuleWizard,
  statusFilter,
  onChangeStatusFilter,
  searchQuery,
  onChangeSearchQuery,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);

  // Keyboard navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't intercept if an input or modal is active
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes((e.target as HTMLElement)?.tagName)) {
        return;
      }

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        onSelectIndex(Math.min(transactions.length - 1, selectedIndex + 1));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        onSelectIndex(Math.max(0, selectedIndex - 1));
      } else if (e.key === 'Enter') {
        e.preventDefault();
        const activeItem = transactions[selectedIndex];
        if (activeItem) {
          if (e.ctrlKey || e.metaKey) {
            // Approve + open rule wizard / learn rule
            onApprove(activeItem.staged_id);
            onOpenRuleWizard(activeItem);
          } else {
            onApprove(activeItem.staged_id);
          }
        }
      } else if (e.key.toLowerCase() === 'r' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        const activeItem = transactions[selectedIndex];
        if (activeItem) onOpenRuleWizard(activeItem);
      } else if (e.key.toLowerCase() === 'x') {
        e.preventDefault();
        const activeItem = transactions[selectedIndex];
        if (activeItem) onReject(activeItem.staged_id);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [selectedIndex, transactions, onSelectIndex, onApprove, onReject, onOpenRuleWizard]);

  // Scroll active row into view
  useEffect(() => {
    const rowEl = document.getElementById(`row-${selectedIndex}`);
    if (rowEl) {
      rowEl.scrollIntoView({ block: 'nearest' });
    }
  }, [selectedIndex]);

  return (
    <div className="flex-1 flex flex-col bg-slate-900 overflow-hidden" ref={containerRef}>
      {/* Table Toolbar */}
      <div className="h-11 px-4 border-b border-slate-800 bg-slate-900/80 flex items-center justify-between gap-3 text-xs shrink-0">
        <div className="flex items-center space-x-2">
          {['all', 'pending', 'categorized', 'approved', 'rejected'].map((st) => (
            <button
              key={st}
              onClick={() => onChangeStatusFilter(st === 'all' ? '' : st)}
              className={`px-2.5 py-1 rounded font-mono uppercase text-[11px] transition-colors ${
                (statusFilter === st || (st === 'all' && !statusFilter))
                  ? 'bg-indigo-600/30 text-indigo-300 border border-indigo-500/40 font-semibold'
                  : 'text-slate-400 hover:bg-slate-800'
              }`}
            >
              {st}
            </button>
          ))}
        </div>

        <div className="flex items-center space-x-2">
          <input
            type="text"
            placeholder="Filter by payee / narration..."
            value={searchQuery}
            onChange={(e) => onChangeSearchQuery(e.target.value)}
            className="w-56 px-2.5 py-1 rounded bg-slate-800 border border-slate-700 text-slate-200 placeholder-slate-500 text-xs focus:outline-none focus:border-indigo-500 font-mono"
          />
        </div>
      </div>

      {/* Grid Header */}
      <div className="grid grid-cols-12 px-4 py-2 border-b border-slate-800 bg-slate-800/40 text-[11px] font-mono text-slate-400 uppercase tracking-wider select-none shrink-0">
        <div className="col-span-2">Date</div>
        <div className="col-span-3">Payee</div>
        <div className="col-span-3">Contra Account</div>
        <div className="col-span-2 text-right">Amount</div>
        <div className="col-span-1 text-center">Match</div>
        <div className="col-span-1 text-right">Actions</div>
      </div>

      {/* Virtual / Scrollable Table Body */}
      <div className="flex-1 overflow-y-auto divide-y divide-slate-800/60 font-mono text-xs">
        {transactions.length === 0 ? (
          <div className="p-12 text-center text-slate-500 flex flex-col items-center justify-center space-y-2">
            <AlertCircle className="w-6 h-6 text-slate-600" />
            <p>No staged transactions matching criteria.</p>
          </div>
        ) : (
          transactions.map((tx, idx) => {
            const isSelected = idx === selectedIndex;
            const contraLeg = tx.postings.find((p) => p.account && !p.account.startsWith('Assets:Bank'))?.account || '—';
            const scale = tx.scale || 2;
            const amountFormatted = (tx.minor_units / 10 ** scale).toFixed(scale);

            // Confidence heatmap badge
            const conf = tx.confidence_score ?? 0;
            let confBadge = 'bg-rose-950 text-rose-400 border-rose-800';
            if (conf >= 0.9) {
              confBadge = 'bg-emerald-950 text-emerald-400 border-emerald-800';
            } else if (conf >= 0.5) {
              confBadge = 'bg-amber-950 text-amber-400 border-amber-800';
            }

            return (
              <div
                key={tx.staged_id}
                id={`row-${idx}`}
                onClick={() => onSelectIndex(idx)}
                className={`grid grid-cols-12 px-4 py-2.5 items-center cursor-pointer transition-colors ${
                  isSelected
                    ? 'bg-indigo-950/40 text-slate-100 border-l-2 border-indigo-500 font-medium'
                    : 'text-slate-300 hover:bg-slate-800/40'
                }`}
              >
                <div className="col-span-2 text-slate-400">{tx.date}</div>
                <div className="col-span-3 truncate text-slate-200" title={tx.payee}>
                  {tx.payee || tx.narration || '(Unnamed)'}
                </div>
                <div className="col-span-3 truncate text-indigo-300/90" title={contraLeg}>
                  {contraLeg}
                </div>
                <div className={`col-span-2 text-right font-mono font-medium ${tx.minor_units < 0 ? 'text-slate-100' : 'text-emerald-400'}`}>
                  {amountFormatted} <span className="text-slate-500 text-[10px]">{tx.currency}</span>
                </div>
                <div className="col-span-1 flex justify-center">
                  <span className={`text-[10px] px-1.5 py-0.2 rounded border font-mono font-bold ${confBadge}`}>
                    {Math.round(conf * 100)}%
                  </span>
                </div>
                <div className="col-span-1 flex justify-end space-x-1">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onApprove(tx.staged_id);
                    }}
                    title="Approve (Enter)"
                    className="p-1 rounded hover:bg-emerald-900/60 text-emerald-400"
                  >
                    <Check className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onOpenSplit(tx);
                    }}
                    title="Split Postings"
                    className="p-1 rounded hover:bg-slate-700 text-slate-400"
                  >
                    <Split className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onReject(tx.staged_id);
                    }}
                    title="Reject (X)"
                    className="p-1 rounded hover:bg-rose-900/60 text-rose-400"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Grid Footer with Keyboard Shortcuts Summary */}
      <div className="h-7 px-4 border-t border-slate-800 bg-slate-900/90 text-[11px] font-mono text-slate-500 flex items-center justify-between shrink-0 select-none">
        <div className="flex items-center space-x-4">
          <span><kbd className="px-1 rounded bg-slate-800 text-slate-300">↑/↓</kbd> Navigate</span>
          <span><kbd className="px-1 rounded bg-slate-800 text-slate-300">Enter</kbd> Approve</span>
          <span><kbd className="px-1 rounded bg-slate-800 text-slate-300">Ctrl+Enter</kbd> Approve & Rule</span>
          <span><kbd className="px-1 rounded bg-slate-800 text-slate-300">Ctrl+R</kbd> Rule Wizard</span>
          <span><kbd className="px-1 rounded bg-slate-800 text-slate-300">X</kbd> Reject</span>
        </div>
        <div>
          {transactions.length} items
        </div>
      </div>
    </div>
  );
};

