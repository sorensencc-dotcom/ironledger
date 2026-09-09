import React, { useEffect, useState } from 'react';
import { Code, Database, PlusCircle } from 'lucide-react';
import { api } from '../api';
import type { RuleDrift, StagedTransaction } from '../types';

interface InspectorSidecarProps {
  transaction: StagedTransaction | null;
  onOpenRuleWizard: (stx: StagedTransaction) => void;
}

export const InspectorSidecar: React.FC<InspectorSidecarProps> = ({
  transaction,
  onOpenRuleWizard,
}) => {
  const [drift, setDrift] = useState<RuleDrift | null>(null);

  useEffect(() => {
    if (transaction?.matched_rule_id) {
      api.getRuleDrift(transaction.matched_rule_id)
        .then((res) => setDrift(res))
        .catch(() => setDrift(null));
    } else {
      setDrift(null);
    }
  }, [transaction?.matched_rule_id]);

  if (!transaction) {
    return (
      <aside className="w-80 border-l border-slate-700 bg-slate-900 p-4 text-slate-500 font-mono text-xs flex items-center justify-center select-none shrink-0">
        Select a transaction to inspect details.
      </aside>
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

  return (
    <aside className="w-84 border-l border-slate-700 bg-slate-900 flex flex-col divide-y divide-slate-800 shrink-0 overflow-y-auto font-sans select-none">
      {/* Inspector Header */}
      <div className="p-3 bg-slate-900/90 flex items-center justify-between">
        <h3 className="font-semibold text-xs text-slate-200 uppercase tracking-wider font-mono flex items-center gap-2">
          <Database className="w-3.5 h-3.5 text-indigo-400" />
          Transaction Inspector
        </h3>
        <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 uppercase">
          {transaction.status}
        </span>
      </div>

      {/* Beancount Syntax Preview Card */}
      <div className="p-3 space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-mono font-medium text-slate-400 flex items-center gap-1.5">
            <Code className="w-3.5 h-3.5 text-indigo-400" />
            Plaintext Beancount Preview
          </span>
          <span className="text-[10px] font-mono text-slate-500">Immutable</span>
        </div>
        <pre className="p-2.5 rounded bg-slate-950 border border-slate-800 text-[11px] font-mono text-emerald-300 overflow-x-auto leading-relaxed whitespace-pre selection:bg-indigo-900 selection:text-white">
          {beancountText}
        </pre>
      </div>

      {/* Rule & Drift Card */}
      <div className="p-3 space-y-2.5 text-xs">
        <div className="flex items-center justify-between">
          <span className="font-mono font-medium text-slate-400">Categorization Rule</span>
          {transaction.matched_rule_id ? (
            <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-indigo-950 text-indigo-300 border border-indigo-800">
              Matched: {transaction.matched_rule_id.slice(0, 10)}...
            </span>
          ) : (
            <span className="text-[10px] font-mono text-slate-500">No Rule Matched</span>
          )}
        </div>

        {drift ? (
          <div className="p-2.5 rounded bg-slate-800/60 border border-slate-700/60 space-y-2 font-mono text-[11px]">
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Drift Status:</span>
              <span
                className={`px-1.5 py-0.2 rounded font-bold uppercase ${
                  drift.drift_status === 'healthy'
                    ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                    : 'bg-amber-950 text-amber-400 border border-amber-800'
                }`}
              >
                {drift.drift_status}
              </span>
            </div>
            <div className="flex items-center justify-between text-slate-400">
              <span>Confidence Trend:</span>
              <span className="text-slate-200">{(drift.confidence_trend * 100).toFixed(0)}%</span>
            </div>
            <div className="flex items-center justify-between text-slate-400">
              <span>Override Rate:</span>
              <span className="text-slate-200">{(drift.override_rate * 100).toFixed(1)}%</span>
            </div>
            <div className="flex items-center justify-between text-slate-400">
              <span>Total Hits:</span>
              <span className="text-slate-200">{drift.total_hits}</span>
            </div>
          </div>
        ) : (
          <div className="p-2.5 rounded bg-slate-800/40 border border-dashed border-slate-700 text-slate-500 text-[11px] flex flex-col items-center justify-center space-y-1">
            <p>No rule learned for this payee yet.</p>
            <button
              onClick={() => onOpenRuleWizard(transaction)}
              className="mt-1 px-2.5 py-1 rounded bg-indigo-600/30 hover:bg-indigo-600/50 text-indigo-300 border border-indigo-500/40 font-mono text-[10px] flex items-center gap-1 transition-colors"
            >
              <PlusCircle className="w-3 h-3" />
              <span>Create Rule (Ctrl+R)</span>
            </button>
          </div>
        )}
      </div>

      {/* Provenance & Evidence Metadata */}
      <div className="p-3 space-y-2 font-mono text-[11px] text-slate-400">
        <span className="text-slate-500 font-bold uppercase tracking-wider text-[10px]">Evidence Provenance</span>
        <div className="space-y-1">
          <div className="flex justify-between">
            <span className="text-slate-500">Document ID:</span>
            <span className="text-slate-300 truncate max-w-[140px]" title={transaction.source_document_id}>
              {transaction.source_document_id}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-500">Record ID:</span>
            <span className="text-slate-300 truncate max-w-[140px]" title={transaction.source_record_id}>
              {transaction.source_record_id}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-500">Staged ID:</span>
            <span className="text-indigo-400 truncate max-w-[140px]" title={transaction.staged_id}>
              {transaction.staged_id}
            </span>
          </div>
        </div>
      </div>
    </aside>
  );
};

