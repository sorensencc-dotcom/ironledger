import React, { useEffect, useRef, useState } from 'react';
import { Check, X, Split, AlertCircle } from 'lucide-react';
import type { Rule, StagedTransaction } from '../types';
import { humanizePayee } from '../lib/text';
import { getCategoryAccount } from '../lib/staging';
import { AccountTypeahead } from './AccountTypeahead';

interface RegisterGridProps {
  transactions: StagedTransaction[];
  selectedIndex: number;
  onSelectIndex: (index: number) => void;
  onApprove: (stagedId: string) => void;
  onReject: (stagedId: string) => void;
  onOpenSplit: (stx: StagedTransaction) => void;
  onOpenRuleWizard: (stx: StagedTransaction) => void;
  onCategorize?: (stagedId: string, targetAccount: string) => void;
  rules: Rule[];
  statusFilter: string;
  onChangeStatusFilter: (status: string) => void;
  searchQuery: string;
  onChangeSearchQuery: (query: string) => void;
  onScanRules?: () => void;
  scanningRules?: boolean;
}

interface RegisterCategoryCellProps {
  categoryAccount?: string;
  rules: Rule[];
  onApply?: (account: string) => void;
}

// Inline categorize control for a staging row: lets an operator retarget the
// posting account and commit it without leaving the row for the inspector,
// mirroring InspectorSidecar's "Categorize this row" + "Apply" pattern.
const RegisterCategoryCellImpl: React.FC<RegisterCategoryCellProps> = ({ categoryAccount, rules, onApply }) => {
  const [value, setValue] = useState(categoryAccount || '');

  useEffect(() => {
    setValue(categoryAccount || '');
  }, [categoryAccount]);

  const dirty = value.trim() !== '' && value.trim() !== (categoryAccount || '');

  return (
    <div className="col-span-3 min-w-0 flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
      <div className="flex-1 min-w-0">
        <AccountTypeahead value={value} onChange={setValue} rules={rules} placeholder="Expenses:Auto" />
      </div>
      {dirty && onApply && (
        <button
          type="button"
          onClick={() => onApply(value.trim())}
          title="Apply category"
          className="shrink-0 p-1.5 rounded-[4px] border border-ember/40 text-ember hover:bg-ember/10 transition-colors"
        >
          <Check className="w-3.5 h-3.5" />
        </button>
      )}
    </div>
  );
};

const RegisterCategoryCell = React.memo(RegisterCategoryCellImpl);

const RegisterGridImpl: React.FC<RegisterGridProps> = ({
  transactions,
  selectedIndex,
  onSelectIndex,
  onApprove,
  onReject,
  onOpenSplit,
  onOpenRuleWizard,
  onCategorize,
  rules,
  statusFilter,
  onChangeStatusFilter,
  searchQuery,
  onChangeSearchQuery,
  onScanRules,
  scanningRules,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const rowHeight = 64;
  const visibleCount = 40;
  const startIndex = Math.max(0, Math.floor(scrollTop / rowHeight) - 5);
  const endIndex = Math.min(transactions.length, startIndex + visibleCount + 10);
  const visibleTransactions = transactions.slice(startIndex, endIndex);

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
        if (activeItem && activeItem.item_type !== 'attach') {
          if (e.ctrlKey || e.metaKey) {
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
        if (activeItem && activeItem.item_type !== 'attach') onReject(activeItem.staged_id);
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
    <div className="flex-1 flex flex-col bg-[#1a1410] border-r border-[rgba(154,144,136,0.12)] overflow-hidden relative" ref={containerRef}>
      {/* Background Depth: Ghost watermark & corner blurred glow */}
      <div className="ghost-watermark" style={{ top: '24px', right: '14px', fontSize: '90px' }}>INBOX</div>
      <div style={{ position: 'absolute', top: '-60px', right: '-40px', width: '260px', height: '260px', background: 'radial-gradient(circle, rgba(90,158,111,0.22), transparent 70%)', filter: 'blur(30px)', pointerEvents: 'none', zIndex: 0 }} />

      {/* Table Toolbar */}
      <div className="h-11 px-4 border-b border-[rgba(139,58,26,0.25)] bg-[#201813] flex items-center justify-between gap-3 text-xs shrink-0 relative z-10">
        <div className="flex items-center space-x-1.5 font-ui tracking-wider uppercase">
          {['all', 'uncategorized', 'pending', 'categorized', 'approved', 'rejected'].map((st) => (
            <button
              key={st}
              onClick={() => onChangeStatusFilter(st === 'all' ? '' : st)}
              className={`px-2.5 py-1 text-[11px] transition-colors ${
                (statusFilter === st || (st === 'all' && !statusFilter))
                  ? 'bg-[rgba(196,80,26,0.15)] text-ember border border-[rgba(196,80,26,0.5)] font-bold'
                  : 'text-ash hover:text-bone hover:bg-card-hover border border-transparent'
              }`}
            >
              {st}
            </button>
          ))}
        </div>

        <div className="flex items-center space-x-2">
          <button
            type="button"
            onClick={onScanRules}
            disabled={!onScanRules || scanningRules}
            className="px-2.5 py-1 text-[11px] font-ui tracking-wider uppercase border border-ember/40 text-ember disabled:opacity-40"
          >
            {scanningRules ? 'Scanning…' : 'Scan rules'}
          </button>
          <input
            type="text"
            placeholder="Filter by payee / narration..."
            value={searchQuery}
            onChange={(e) => onChangeSearchQuery(e.target.value)}
            className="w-56 px-2.5 py-1 bg-black/60 border border-border text-bone placeholder-ash/70 text-xs focus:outline-none focus:border-ember font-ui tracking-wider"
          />
        </div>
      </div>

      {/* Grid Header */}
      <div className="grid grid-cols-12 px-4 py-2 border-b border-[rgba(139,58,26,0.2)] bg-[#140f0c] text-[11px] font-ui text-ash uppercase tracking-[0.2em] select-none shrink-0 relative z-10">
        <div className="col-span-2">Date</div>
        <div className="col-span-3">Payee</div>
        <div className="col-span-3">Category / Subcategory</div>
        <div className="col-span-2 text-right">Amount</div>
        <div className="col-span-1 text-center">Match</div>
        <div className="col-span-1 text-right">Actions</div>
      </div>

      {/* Virtual / Scrollable Table Body */}
      <div className="flex-1 overflow-y-auto divide-y divide-[rgba(154,144,136,0.08)] relative z-10" onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}>
        {transactions.length === 0 ? (
          <div className="p-12 text-center text-ash flex flex-col items-center justify-center space-y-2">
            <AlertCircle className="w-6 h-6 text-rust" />
            <p className="font-serif italic text-sm">No staged transactions matching criteria.</p>
          </div>
        ) : (
          <>
          <div style={{ height: startIndex * rowHeight }} />
          {visibleTransactions.map((tx, visibleIndex) => {
            const idx = startIndex + visibleIndex;
            const isSelected = idx === selectedIndex;
            const categoryAccount = getCategoryAccount(tx);
            const scale = tx.scale || 2;
            const rawAmount = tx.minor_units / 10 ** scale;
            const isNegative = tx.minor_units < 0;
            const amountFormatted = isNegative
              ? `-${Math.abs(rawAmount).toFixed(scale)}`
              : `+${rawAmount.toFixed(scale)}`;

            // Confidence score color rule
            const conf = tx.confidence_score ?? 0;
            const confColor = conf >= 0.7 ? 'text-gain-bright' : 'text-loss-bright';

            return (
              <div
                key={tx.staged_id}
                id={`row-${idx}`}
                onClick={() => onSelectIndex(idx)}
                className={`grid grid-cols-12 px-4 py-2.5 items-center cursor-pointer transition-colors ${
                  isSelected
                    ? 'bg-[rgba(139,58,26,0.1)] text-white border-l-2 border-ember font-medium'
                    : 'text-bone hover:bg-card-hover/80'
                }`}
              >
                <div className="col-span-2 font-ui text-xs text-ash tracking-wider">{tx.date}</div>
                <div className="col-span-3 min-w-0 line-clamp-2 break-words font-serif font-bold text-xs text-white" title={tx.payee}>
                  {tx.item_type === 'attach' ? (
                    <span className="text-ember uppercase text-[10px] tracking-wider mr-1">
                      {tx.attach_kind === 'near_miss' ? 'near-miss' : 'attach'}
                    </span>
                  ) : null}
                  {tx.payee ? humanizePayee(tx.payee) : (tx.narration || '(Unnamed)')}
                </div>
                <RegisterCategoryCell
                  categoryAccount={categoryAccount}
                  rules={rules}
                  onApply={onCategorize ? (account) => onCategorize(tx.staged_id, account) : undefined}
                />
                <div className={`col-span-2 text-right font-ui font-extrabold text-sm ${isNegative ? 'text-loss-bright' : 'text-gain-bright'}`}>
                  {amountFormatted} <span className="text-ash font-normal text-[10px] tracking-wider uppercase">{tx.currency}</span>
                </div>
                <div className="col-span-1 flex justify-center">
                  <span className={`text-[12px] font-ui font-bold tracking-wider ${confColor}`}>
                    {Math.round(conf * 100)}%
                  </span>
                </div>
                <div className="col-span-1 flex justify-end space-x-1">
                  {tx.item_type !== 'attach' && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onApprove(tx.staged_id);
                    }}
                    title="Approve (Enter)"
                    className="p-1 hover:bg-gain-tint text-gain-bright transition-colors"
                  >
                    <Check className="w-3.5 h-3.5" />
                  </button>
                  )}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onOpenSplit(tx);
                    }}
                    title="Split Postings"
                    className="p-1 hover:bg-card-hover text-ash hover:text-white transition-colors"
                  >
                    <Split className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onReject(tx.staged_id);
                    }}
                    title="Reject (X)"
                    className="p-1 hover:bg-loss-tint text-loss-bright transition-colors"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            );
          })}
          <div style={{ height: Math.max(0, (transactions.length - endIndex) * rowHeight) }} />
          </>
        )}
      </div>

      {/* Grid Footer with Keyboard Shortcuts Summary */}
      <div className="h-7 px-4 border-t border-[rgba(154,144,136,0.12)] bg-[#100c0a] text-[11px] font-ui text-ash uppercase tracking-wider flex items-center justify-between shrink-0 select-none relative z-10">
        <div className="flex items-center space-x-4">
          <span><kbd className="px-1 bg-card border border-border text-bone">↑/↓</kbd> Navigate</span>
          <span><kbd className="px-1 bg-card border border-border text-bone">Enter</kbd> Approve</span>
          <span><kbd className="px-1 bg-card border border-border text-bone">Ctrl+Enter</kbd> Approve &amp; Rule</span>
          <span><kbd className="px-1 bg-card border border-border text-bone">Ctrl+R</kbd> Rule Wizard</span>
          <span><kbd className="px-1 bg-card border border-border text-bone">X</kbd> Reject</span>
        </div>
        <div>
          {transactions.length} items
        </div>
      </div>
    </div>
  );
};

export const RegisterGrid = React.memo(RegisterGridImpl);

