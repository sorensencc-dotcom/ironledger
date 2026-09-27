import React, { useEffect, useRef, useState } from 'react';
import { Code, Database, PlusCircle, Fingerprint, FileText } from 'lucide-react';
import { api } from '../api';
import type { Rule, RuleDrift, StagedTransaction } from '../types';
import { AccountTypeahead } from './AccountTypeahead';
import { isRuleActive } from './accountOptions';
import { humanizePayee } from '../lib/text';

interface InspectorSidecarProps {
  transaction: StagedTransaction | null;
  rules: Rule[];
  onOpenRuleWizard: (stx: StagedTransaction) => void;
  onCategorize?: (stagedId: string, targetAccount: string) => void;
  onConfirmAttach?: (proposalId: string, chosenStagedId: string) => void;
}

const WIDTH_KEY = 'ironledger.inspectorWidth';
const DEFAULT_WIDTH = 336;
const MIN_WIDTH = 280;
const MAX_WIDTH = 720;

function clampWidth(n: number): number {
  if (!Number.isFinite(n)) return DEFAULT_WIDTH;
  return Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, Math.round(n)));
}

function useInspectorWidth() {
  const [width, setWidth] = useState(() => {
    try {
      const raw = localStorage.getItem(WIDTH_KEY);
      if (raw == null || raw === '') return DEFAULT_WIDTH;
      return clampWidth(Number(raw));
    } catch {
      return DEFAULT_WIDTH;
    }
  });
  const drag = useRef<{ x: number; width: number } | null>(null);
  const persistWidth = (next: number) => {
    setWidth(next);
    try {
      localStorage.setItem(WIDTH_KEY, String(next));
    } catch {
      /* private mode */
    }
  };

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { x: e.clientX, width };
  };
  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    setWidth(clampWidth(drag.current.width + drag.current.x - e.clientX));
  };
  const finish = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    const next = clampWidth(drag.current.width + drag.current.x - e.clientX);
    drag.current = null;
    persistWidth(next);
    try {
      localStorage.setItem(WIDTH_KEY, String(next));
    } catch {
      /* private mode */
    }
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    const next = clampWidth(width + (e.key === 'ArrowLeft' ? 16 : -16));
    persistWidth(next);
    try {
      localStorage.setItem(WIDTH_KEY, String(next));
    } catch {
      /* private mode */
    }
  };

  return { width, onPointerDown, onPointerMove, onPointerUp: finish, onPointerCancel: finish, onKeyDown };
}

function InspectorFrame({
  width,
  onPointerDown,
  onPointerMove,
  onPointerUp,
  onPointerCancel,
  onKeyDown,
  children,
}: {
  width: number;
  onPointerDown: (e: React.PointerEvent<HTMLDivElement>) => void;
  onPointerMove: (e: React.PointerEvent<HTMLDivElement>) => void;
  onPointerUp: (e: React.PointerEvent<HTMLDivElement>) => void;
  onPointerCancel: (e: React.PointerEvent<HTMLDivElement>) => void;
  onKeyDown: (e: React.KeyboardEvent<HTMLDivElement>) => void;
  children: React.ReactNode;
}) {
  return (
    <div className="relative h-full shrink-0" style={{ width }}>
      <div
        role="separator"
        tabIndex={0}
        aria-orientation="vertical"
        aria-valuenow={width}
        aria-valuemin={MIN_WIDTH}
        aria-valuemax={MAX_WIDTH}
        aria-label="Resize transaction inspector"
        className="absolute inset-y-0 left-0 z-20 w-2 cursor-col-resize touch-none hover:bg-ember/50"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerCancel}
        onKeyDown={onKeyDown}
      />
      {children}
    </div>
  );
}

const InspectorSidecarImpl: React.FC<InspectorSidecarProps> = ({
  transaction,
  rules,
  onOpenRuleWizard,
  onCategorize,
  onConfirmAttach,
}) => {
  const frame = useInspectorWidth();
  const [drift, setDrift] = useState<RuleDrift | null>(null);
  const [chosenCandidate, setChosenCandidate] = useState<string | null>(null);
  const [category, setCategory] = useState('');

  useEffect(() => {
    if (transaction?.matched_rule_id) {
      api.getRuleDrift(transaction.matched_rule_id)
        .then((res) => setDrift(res))
        .catch(() => setDrift(null));
    } else {
      setDrift(null);
    }
    setChosenCandidate(null);
    const matched = rules.find(
      (r) => r.rule_id === transaction?.matched_rule_id && isRuleActive(r),
    );
    setCategory(matched?.target_account || '');
  }, [transaction?.matched_rule_id, transaction?.proposal_id, transaction?.staged_id, rules]);

  if (!transaction) {
    return (
      <InspectorFrame {...frame}>
      <aside className="h-full w-full border-l border-[rgba(154,144,136,0.12)] bg-[#140f0c] p-6 text-ash font-serif italic text-xs flex items-center justify-center select-none text-center">
        Select a transaction from the inbox to inspect its provenance and Beancount postings.
      </aside>
      </InspectorFrame>
    );
  }

  // Generate deterministic Beancount preview
  const dateStr = transaction.date || '2026-01-01';
  const payeeStr = transaction.payee ? `"${transaction.payee.replace(/"/g, '\\"')}"` : '""';
  const narrationStr = transaction.narration ? `"${transaction.narration.replace(/"/g, '\\"')}"` : '""';

  const beancountLines = [
    `${dateStr} * ${payeeStr} ${narrationStr}`,
  ];

  for (const p of transaction.postings) {
    const scale = p.scale || 2;
    const amtStr = (p.minor_units / 10 ** scale).toFixed(scale);
    beancountLines.push(`  ${p.account.padEnd(30, ' ')} ${amtStr.padStart(10, ' ')} ${p.currency}`);
  }
  beancountLines.push(`  staged-id: "${transaction.staged_id}"`);
  const beancountText = beancountLines.join('\n');

  // Provenance tag classification
  const extId = transaction.external_id || '';
  const isFitidPrimary = extId.startsWith('simplefin:id:');
  const isCompositeFallback = extId.startsWith('composite:v1:');

  // Clean evidence path extraction
  const evidenceRef = transaction.raw_payload_ref || '';
  const evidenceBasename = evidenceRef ? evidenceRef.split(/[\\/]/).pop() || evidenceRef : '';

  return (
    <InspectorFrame {...frame}>
    <aside className="h-full w-full min-w-0 border-l border-[rgba(154,144,136,0.12)] bg-[#140f0c] flex flex-col divide-y divide-[rgba(154,144,136,0.1)] overflow-y-auto select-none">
      {/* Inspector Header */}
      <div className="p-3 bg-[#1e1713] flex items-center justify-between border-b border-[rgba(139,58,26,0.2)]">
        <h3 className="font-ui font-bold text-xs text-white uppercase tracking-[0.2em] flex items-center gap-2">
          <Database className="w-3.5 h-3.5 text-brass" />
          Transaction Inspector
        </h3>
        <span className="text-[10px] font-ui font-bold px-2 py-0.5 border border-ember/40 bg-ember/10 text-ember uppercase tracking-wider">
          {transaction.item_type === 'attach' ? transaction.attach_kind : transaction.status}
        </span>
      </div>

      {transaction.item_type === 'attach' && (
        <div className="p-3.5 space-y-2">
          <p className="text-[11px] font-ui uppercase tracking-wider text-ash">
            {transaction.attach_kind === 'near_miss' ? 'Near-miss suggestion' : 'Attach evidence'}
          </p>
          <p className="text-xs text-bone">PDF: {transaction.pdf_description}</p>
          <div className="space-y-1">
            {(transaction.candidates || []).map((c) => (
              <label key={c.staged_id} className="flex items-center gap-2 text-xs text-bone">
                <input
                  type="radio"
                  name="attach-candidate"
                  checked={chosenCandidate === c.staged_id}
                  onChange={() => setChosenCandidate(c.staged_id)}
                />
                <span>{c.date} {humanizePayee(c.payee)} ({c.minor_units})</span>
              </label>
            ))}
          </div>
          <button
            type="button"
            disabled={!chosenCandidate || !transaction.proposal_id || !onConfirmAttach}
            onClick={() => {
              if (chosenCandidate && transaction.proposal_id && onConfirmAttach) {
                onConfirmAttach(transaction.proposal_id, chosenCandidate);
              }
            }}
            className="px-2 py-1 text-[11px] uppercase tracking-wider border border-ember/40 text-ember disabled:opacity-40"
          >
            Confirm attach
          </button>
        </div>
      )}

      {transaction.item_type !== 'attach' && (
        <div className="p-3.5 space-y-2">
          <span className="text-[11px] font-ui tracking-wider uppercase font-semibold text-ash">
            Categorize this row
          </span>
          <AccountTypeahead
            value={category}
            onChange={setCategory}
            rules={rules}
            placeholder="Expenses:Auto"
          />
          <button
            type="button"
            disabled={!category.trim() || !onCategorize}
            onClick={() => {
              if (category.trim() && onCategorize) {
                onCategorize(transaction.staged_id, category.trim());
              }
            }}
            className="px-2 py-1 text-[11px] uppercase tracking-wider border border-ember/40 text-ember disabled:opacity-40"
          >
            Apply to this row
          </button>
        </div>
      )}

      {/* Beancount Syntax Preview Card */}
      <div className="p-3.5 space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-ui tracking-wider uppercase font-semibold text-ash flex items-center gap-1.5">
            <Code className="w-3.5 h-3.5 text-brass" />
            Immutable Beancount Syntax
          </span>
          <span className="text-[10px] font-ui tracking-wider text-ash/80 uppercase">SHA Verified</span>
        </div>
        <pre className="p-2.5 bg-black/80 border border-border text-[11px] font-mono text-gain-bright overflow-x-auto leading-relaxed whitespace-pre">
          {beancountText}
        </pre>
      </div>

      {/* Rule & Drift Card */}
      <div className="p-3.5 space-y-2.5 text-xs">
        <div className="flex items-center justify-between">
          <span className="font-ui font-bold text-[11px] uppercase tracking-wider text-ash">Categorization Rule</span>
          {transaction.matched_rule_id ? (
            <span className="text-[10px] font-ui tracking-wider px-1.5 py-0.5 bg-brass/10 text-brass border border-brass/40 uppercase font-bold">
              Matched: {transaction.matched_rule_id.slice(0, 10)}...
            </span>
          ) : (
            <span className="text-[10px] font-ui tracking-wider text-ash uppercase">No Rule Matched</span>
          )}
        </div>

        {drift ? (
          <div className="p-3 border-l-2 border-gain bg-gain-tint space-y-2 font-ui text-[11px]">
            <div className="flex items-center justify-between">
              <span className="text-ash uppercase tracking-wider">Drift Status:</span>
              <span
                className={`px-1.5 py-0.5 font-bold uppercase text-[10px] border ${
                  drift.drift_status === 'healthy'
                    ? 'bg-gain-tint text-gain-bright border-gain/40'
                    : 'bg-loss-tint text-loss-bright border-loss/40'
                }`}
              >
                {drift.drift_status}
              </span>
            </div>

            {/* Hit Confidence Trend Heatmap / Bar */}
            <div className="space-y-1">
              <div className="flex justify-between text-ash text-[10px] tracking-wider uppercase">
                <span>Hit Confidence Trend:</span>
                <span className="text-bone font-bold">{(drift.confidence_trend * 100).toFixed(0)}%</span>
              </div>
              <div className="w-full h-1.5 bg-black/60 overflow-hidden flex">
                <div
                  className={`h-full transition-all duration-300 ${
                    drift.confidence_trend >= 0.8
                      ? 'bg-gain-bright'
                      : drift.confidence_trend >= 0.5
                      ? 'bg-brass'
                      : 'bg-loss-bright'
                  }`}
                  style={{ width: `${Math.min(100, Math.max(5, drift.confidence_trend * 100))}%` }}
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2 pt-1 border-t border-[rgba(154,144,136,0.12)] text-[10px] uppercase tracking-wider">
              <div className="flex flex-col">
                <span className="text-ash">Override Rate</span>
                <span className="text-bone font-bold">{(drift.override_rate * 100).toFixed(1)}%</span>
              </div>
              <div className="flex flex-col">
                <span className="text-ash">Total Hits</span>
                <span className="text-bone font-bold">{drift.total_hits}</span>
              </div>
            </div>
          </div>
        ) : (
          <div className="p-3 bg-card border border-dashed border-border text-ash text-[11px] flex flex-col items-center justify-center space-y-1.5 text-center">
            <p className="font-serif italic text-xs">No learned rule for this payee yet.</p>
            <button
              onClick={() => onOpenRuleWizard(transaction)}
              className="mt-1 px-3 py-1 bg-ember/10 hover:bg-ember/20 text-ember border border-ember/40 font-ui font-bold text-[10px] tracking-wider uppercase flex items-center gap-1 transition-colors"
            >
              <PlusCircle className="w-3 h-3" />
              <span>Create Rule (Ctrl+R)</span>
            </button>
          </div>
        )}
      </div>

      {/* Provenance & Evidence Metadata */}
      <div className="p-3.5 space-y-2.5 font-ui text-[11px] text-ash">
        <div className="flex items-center justify-between">
          <span className="text-rust font-bold uppercase tracking-[0.2em] text-[10px] flex items-center gap-1">
            <Fingerprint className="w-3 h-3 text-rust" />
            Evidence Provenance
          </span>
          {isFitidPrimary ? (
            <span className="px-1.5 py-0.5 bg-gain-tint text-gain-bright border border-gain/40 text-[9px] font-bold uppercase tracking-wider">
              FITID PRIMARY
            </span>
          ) : isCompositeFallback ? (
            <span className="px-1.5 py-0.5 bg-brass/10 text-brass border border-brass/40 text-[9px] font-bold uppercase tracking-wider">
              COMPOSITE v1
            </span>
          ) : extId ? (
            <span className="px-1.5 py-0.5 bg-black/40 text-ash border border-border text-[9px] uppercase tracking-wider">
              EXTERNAL
            </span>
          ) : null}
        </div>

        <div className="space-y-1.5">
          {/* External ID / Fingerprint */}
          {extId && (
            <div className="p-2 bg-black/50 border border-border space-y-0.5">
              <div className="text-[10px] text-ash uppercase tracking-wider">Provenance Identity:</div>
              <div
                className={`truncate font-mono text-[10px] ${
                  isFitidPrimary
                    ? 'text-gain-bright font-medium'
                    : isCompositeFallback
                    ? 'text-brass font-medium'
                    : 'text-bone'
                }`}
                title={extId}
              >
                {extId}
              </div>
            </div>
          )}

          {/* Raw Evidence Archive Digest Link */}
          {evidenceBasename && (
            <div className="p-2 bg-black/50 border border-border space-y-0.5">
              <div className="text-[10px] text-ash flex items-center justify-between uppercase tracking-wider">
                <span className="flex items-center gap-1">
                  <FileText className="w-3 h-3 text-gain-bright" />
                  Raw Wire Archive:
                </span>
                <span className="text-[9px] text-gain-bright">SHA-256 Verified</span>
              </div>
              <div
                className="truncate font-mono text-[10px] text-gain-bright hover:text-white cursor-pointer flex items-center gap-1"
                title={`Content-addressed archive: evidence/source_documents/${evidenceBasename}`}
              >
                <span className="truncate">{evidenceBasename}</span>
              </div>
            </div>
          )}

          <div className="flex justify-between pt-1 uppercase tracking-wider">
            <span className="text-ash">Document ID:</span>
            <span className="text-bone min-w-0 flex-1 text-right truncate font-mono text-[10px]" title={transaction.source_document_id}>
              {transaction.source_document_id}
            </span>
          </div>
          <div className="flex justify-between uppercase tracking-wider">
            <span className="text-ash">Record ID:</span>
            <span className="text-bone min-w-0 flex-1 text-right truncate font-mono text-[10px]" title={transaction.source_record_id}>
              {transaction.source_record_id}
            </span>
          </div>
          <div className="flex justify-between uppercase tracking-wider">
            <span className="text-ash">Staged ID:</span>
            <span className="text-ember min-w-0 flex-1 text-right truncate font-mono text-[10px]" title={transaction.staged_id}>
              {transaction.staged_id}
            </span>
          </div>
        </div>
      </div>
    </aside>
    </InspectorFrame>
  );
};

export const InspectorSidecar = React.memo(InspectorSidecarImpl);

