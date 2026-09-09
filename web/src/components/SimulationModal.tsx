import React from 'react';
import { X, Play, ShieldCheck } from 'lucide-react';
import type { CompileResult } from '../types';

interface SimulationModalProps {
  isOpen: boolean;
  onClose: () => void;
  result: CompileResult | null;
  loading: boolean;
}

export const SimulationModal: React.FC<SimulationModalProps> = ({
  isOpen,
  onClose,
  result,
  loading,
}) => {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4 select-none font-sans">
      <div className="w-full max-w-2xl bg-slate-900 border border-slate-700 rounded-lg shadow-2xl overflow-hidden flex flex-col max-h-[85vh]">
        {/* Header */}
        <div className="px-5 py-4 border-b border-slate-800 flex items-center justify-between bg-slate-850 shrink-0">
          <div className="flex items-center space-x-2.5">
            <ShieldCheck className="w-4 h-4 text-emerald-400" />
            <h3 className="font-semibold text-sm text-slate-100">Safe Mode Dry-Run Simulation</h3>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-200">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Content */}
        <div className="p-5 flex-1 overflow-y-auto space-y-4 font-mono text-xs">
          {loading ? (
            <div className="p-12 text-center text-slate-400 flex flex-col items-center justify-center space-y-2">
              <Play className="w-6 h-6 animate-pulse text-indigo-400" />
              <p>Simulating compilation in memory...</p>
            </div>
          ) : result ? (
            <>
              {/* Summary Stats Pill Grid */}
              <div className="grid grid-cols-3 gap-3">
                <div className="p-3 rounded bg-slate-800/60 border border-slate-700/60">
                  <span className="text-[10px] text-slate-500 uppercase">Entries Staged</span>
                  <div className="text-base font-bold text-slate-100">{result.entries_compiled}</div>
                </div>
                <div className="p-3 rounded bg-slate-800/60 border border-slate-700/60">
                  <span className="text-[10px] text-slate-500 uppercase">Postings</span>
                  <div className="text-base font-bold text-slate-100">{result.postings_compiled}</div>
                </div>
                <div className="p-3 rounded bg-emerald-950/30 border border-emerald-800/40">
                  <span className="text-[10px] text-emerald-400 uppercase">Disk Mutations</span>
                  <div className="text-base font-bold text-emerald-300">0 BYTES</div>
                </div>
              </div>

              {/* Diff Preview */}
              <div className="space-y-1.5">
                <span className="text-slate-400 uppercase text-[10px]">Deterministic Unified Diff Preview</span>
                <pre className="p-3 rounded bg-slate-950 border border-slate-800 text-[11px] text-emerald-300 overflow-x-auto max-h-72 leading-relaxed whitespace-pre font-mono">
                  {result.diff_preview || 'No file diffs generated.'}
                </pre>
              </div>
            </>
          ) : (
            <div className="p-8 text-center text-slate-500">
              No simulation results available.
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-slate-800 bg-slate-850 flex justify-end shrink-0">
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium transition-colors"
          >
            Dismiss
          </button>
        </div>
      </div>
    </div>
  );
};

