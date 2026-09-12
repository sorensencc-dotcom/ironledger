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
    <div className="fixed inset-0 bg-black/75 backdrop-blur-md z-50 flex items-center justify-center p-4 select-none font-sans">
      <div className="w-full max-w-2xl bg-[#1a1410] border border-[#3a2e26] rounded-none shadow-2xl overflow-hidden flex flex-col max-h-[85vh] relative">
        {/* Ghost Watermark */}
        <div className="ghost-watermark text-[6rem] -top-8 -right-4 select-none pointer-events-none">
          SAFE
        </div>

        {/* Header */}
        <div className="px-5 py-3.5 border-b border-[#2c2420] flex items-center justify-between bg-[#241c16] shrink-0 relative z-10">
          <div className="flex items-center space-x-2.5">
            <ShieldCheck className="w-4 h-4 text-[#8fc79e]" />
            <h3 className="font-serif font-bold text-sm text-[#f2ece2] tracking-wide">
              Safe Mode Dry-Run Simulation
            </h3>
          </div>
          <button onClick={onClose} className="text-[#7a6e65] hover:text-[#f2ece2] transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Content */}
        <div className="p-5 flex-1 overflow-y-auto space-y-4 font-mono text-xs relative z-10">
          {loading ? (
            <div className="p-12 text-center text-[#a89e94] flex flex-col items-center justify-center space-y-2">
              <Play className="w-6 h-6 animate-pulse text-[#c4501a]" />
              <p>Simulating compilation in memory...</p>
            </div>
          ) : result ? (
            <>
              {/* Summary Stats Pill Grid */}
              <div className="grid grid-cols-3 gap-3">
                <div className="p-3 rounded-none bg-[#130f0c] border border-[#2c2420] border-l-2 border-l-[#b8922a]">
                  <span className="text-[10px] text-[#7a6e65] uppercase font-sans font-bold tracking-wider">Entries Staged</span>
                  <div className="text-base font-bold text-[#f2ece2] mt-0.5">{result.entries_compiled}</div>
                </div>
                <div className="p-3 rounded-none bg-[#130f0c] border border-[#2c2420] border-l-2 border-l-[#b8922a]">
                  <span className="text-[10px] text-[#7a6e65] uppercase font-sans font-bold tracking-wider">Postings</span>
                  <div className="text-base font-bold text-[#f2ece2] mt-0.5">{result.postings_compiled}</div>
                </div>
                <div className="p-3 rounded-none bg-[#132a1c] border border-[#1d442b] border-l-2 border-l-[#8fc79e]">
                  <span className="text-[10px] text-[#8fc79e] uppercase font-sans font-bold tracking-wider">Disk Mutations</span>
                  <div className="text-base font-bold text-[#8fc79e] mt-0.5">0 BYTES</div>
                </div>
              </div>

              {/* Diff Preview */}
              <div className="space-y-1.5">
                <span className="text-[#a89e94] uppercase text-[10px] font-sans font-bold tracking-wider">
                  Deterministic Unified Diff Preview
                </span>
                <pre className="p-3 rounded-none bg-[#0d0a08] border border-[#2c2420] text-[11px] text-[#8fc79e] overflow-x-auto max-h-72 leading-relaxed whitespace-pre font-mono">
                  {result.diff_preview || 'No file diffs generated.'}
                </pre>
              </div>
            </>
          ) : (
            <div className="p-8 text-center text-[#7a6e65]">
              No simulation results available.
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-[#2c2420] bg-[#241c16] flex justify-end shrink-0 relative z-10">
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded-none bg-[#1a1410] hover:bg-[#2c2420] border border-[#3a2e26] text-[#e8dfd1] text-xs font-mono uppercase tracking-wider transition-colors"
          >
            Dismiss
          </button>
        </div>
      </div>
    </div>
  );
};

