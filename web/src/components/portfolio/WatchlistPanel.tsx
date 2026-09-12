import React, { useState } from 'react';
import { RefreshCw, Plus, Activity, CheckCircle2, AlertTriangle, XCircle, ArrowUpDown } from 'lucide-react';
import type { WatchlistData, WatchlistItem, PriceAuditRecord } from '../../types';

interface WatchlistPanelProps {
  data: WatchlistData | null;
  loading: boolean;
  onSync: () => Promise<void>;
  onAddSymbol: (symbol: string, quoteCurrency: string, manualQuote?: string) => Promise<void>;
}

export const WatchlistPanel: React.FC<WatchlistPanelProps> = ({
  data,
  loading,
  onSync,
  onAddSymbol,
}) => {
  const [syncing, setSyncing] = useState(false);
  const [isAdding, setIsAdding] = useState(false);
  const [newSymbol, setNewSymbol] = useState('');
  const [newQuote, setNewQuote] = useState('USD');
  const [newManualQuote, setNewManualQuote] = useState('');
  const [addingError, setAddingError] = useState<string | null>(null);

  const handleSync = async () => {
    try {
      setSyncing(true);
      await onSync();
    } finally {
      setSyncing(false);
    }
  };

  const handleAddSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newSymbol.trim()) return;
    try {
      setAddingError(null);
      await onAddSymbol(newSymbol.trim(), newQuote.trim(), newManualQuote.trim() || undefined);
      setNewSymbol('');
      setNewManualQuote('');
      setIsAdding(false);
    } catch (err: any) {
      setAddingError(err.message || 'Failed to add symbol');
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'SUCCESS':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-950/80 text-emerald-400 border border-emerald-800/60">
            <CheckCircle2 className="w-3 h-3 text-emerald-400" />
            SUCCESS
          </span>
        );
      case 'RECIPROCAL_SUCCESS':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-blue-950/80 text-blue-400 border border-blue-800/60">
            <ArrowUpDown className="w-3 h-3 text-blue-400" />
            RECIPROCAL
          </span>
        );
      case 'CIRCUIT_OPEN':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-rose-950/80 text-rose-400 border border-rose-800/60">
            <XCircle className="w-3 h-3 text-rose-400" />
            CIRCUIT OPEN
          </span>
        );
      case 'STALE_CACHED':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-amber-950/80 text-amber-400 border border-amber-800/60">
            <AlertTriangle className="w-3 h-3 text-amber-400" />
            STALE
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-zinc-900 text-zinc-400 border border-zinc-800">
            {status}
          </span>
        );
    }
  };

  const items = data?.items || [];
  const audit = data?.recent_audit || [];

  return (
    <div className="space-y-4 font-mono">
      {/* Watchlist Table Card */}
      <div className="bg-zinc-950 border border-zinc-800 rounded-lg p-4">
        <div className="flex flex-col sm:flex-row justify-between sm:items-center gap-3 pb-3 mb-3 border-b border-zinc-800">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs uppercase text-zinc-400 font-bold tracking-wider">
                Active Price Watchlist
              </span>
              <span className="text-[10px] px-2 py-0.2 rounded bg-indigo-950 text-indigo-300 border border-indigo-800/60 font-bold">
                {items.length} PAIRS
              </span>
            </div>
            <p className="text-[11px] text-zinc-500 mt-0.5">
              Exact-rational market price resolution with dual Beancount &amp; SQLite persistence
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setIsAdding(!isAdding)}
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded text-xs bg-zinc-900 hover:bg-zinc-800 text-zinc-300 border border-zinc-700 transition-colors"
            >
              <Plus className="w-3.5 h-3.5 text-zinc-400" />
              <span>Add Symbol</span>
            </button>
            <button
              onClick={handleSync}
              disabled={syncing || loading}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white transition-all shadow-sm ${
                syncing ? 'opacity-70 cursor-not-allowed' : ''
              }`}
            >
              <RefreshCw className={`w-3.5 h-3.5 ${syncing ? 'animate-spin' : ''}`} />
              <span>{syncing ? 'Syncing Feeds...' : 'Sync Watchlist'}</span>
            </button>
          </div>
        </div>

        {/* Inline Add Symbol Form */}
        {isAdding && (
          <form onSubmit={handleAddSubmit} className="mb-4 p-3 bg-zinc-900/70 border border-zinc-800 rounded-md space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-zinc-200">Add Watchlist Target Pair</span>
              {addingError && <span className="text-xs text-rose-400">{addingError}</span>}
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
              <div>
                <label className="text-[10px] text-zinc-400 block mb-1">Base Commodity (e.g. NVDA, SOL)</label>
                <input
                  type="text"
                  placeholder="AAPL"
                  value={newSymbol}
                  onChange={(e) => setNewSymbol(e.target.value)}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded px-2.5 py-1.5 text-xs text-zinc-100 uppercase focus:outline-none focus:border-indigo-500"
                  required
                />
              </div>
              <div>
                <label className="text-[10px] text-zinc-400 block mb-1">Quote Currency</label>
                <input
                  type="text"
                  placeholder="USD"
                  value={newQuote}
                  onChange={(e) => setNewQuote(e.target.value)}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded px-2.5 py-1.5 text-xs text-zinc-100 uppercase focus:outline-none focus:border-indigo-500"
                />
              </div>
              <div>
                <label className="text-[10px] text-zinc-400 block mb-1">Fallback Quote ($)</label>
                <input
                  type="text"
                  placeholder="225.50 (optional)"
                  value={newManualQuote}
                  onChange={(e) => setNewManualQuote(e.target.value)}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded px-2.5 py-1.5 text-xs text-zinc-100 focus:outline-none focus:border-indigo-500"
                />
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={() => setIsAdding(false)}
                className="px-2.5 py-1 rounded text-xs bg-zinc-800 text-zinc-400 hover:text-zinc-200"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="px-3 py-1 rounded text-xs bg-indigo-600 hover:bg-indigo-500 text-white font-medium"
              >
                Save Symbol
              </button>
            </div>
          </form>
        )}

        {/* Watchlist Table */}
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-zinc-500 border-b border-zinc-900">
              <tr>
                <th className="py-2">Symbol</th>
                <th className="py-2">Quote</th>
                <th className="py-2 text-right">Latest Price</th>
                <th className="py-2 text-right">Rational (N/D)</th>
                <th className="py-2 text-center">Provider</th>
                <th className="py-2 text-center">Status</th>
                <th className="py-2 text-right">Latency</th>
                <th className="py-2 text-right">As Of Date</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-900 text-zinc-300">
              {items.length === 0 ? (
                <tr>
                  <td colSpan={8} className="py-6 text-center text-zinc-500">
                    No watchlist symbols configured in config/prices.json.
                  </td>
                </tr>
              ) : (
                items.map((item: WatchlistItem) => (
                  <tr key={`${item.symbol}-${item.quote_currency}`} className="hover:bg-zinc-900/50 transition-colors">
                    <td className="py-2.5 font-bold text-white flex items-center gap-1.5">
                      <span className="w-1.5 h-1.5 rounded-full bg-indigo-400"></span>
                      {item.symbol}
                    </td>
                    <td className="py-2.5 text-zinc-400">{item.quote_currency}</td>
                    <td className="py-2.5 text-right font-bold text-zinc-100">
                      {item.price_display ? `$${item.price_display}` : <span className="text-zinc-600">—</span>}
                    </td>
                    <td className="py-2.5 text-right text-zinc-400 font-mono text-[11px]">
                      {item.rate_numerator && item.rate_denominator ? (
                        <span className="bg-zinc-900 px-1.5 py-0.5 rounded border border-zinc-800">
                          {item.rate_numerator}/{item.rate_denominator}
                        </span>
                      ) : (
                        <span className="text-zinc-600">—</span>
                      )}
                    </td>
                    <td className="py-2.5 text-center text-zinc-400">
                      <span className="text-[11px] px-1.5 py-0.5 rounded bg-zinc-900 border border-zinc-800">
                        {item.last_provider}
                      </span>
                    </td>
                    <td className="py-2.5 text-center">{getStatusBadge(item.last_status)}</td>
                    <td className="py-2.5 text-right text-zinc-400">
                      {item.last_latency_ms != null ? `${item.last_latency_ms}ms` : '0ms'}
                    </td>
                    <td className="py-2.5 text-right text-zinc-500 text-[11px]">
                      {item.directive_date || (item.updated_at ? item.updated_at.slice(0, 10) : '—')}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Resolution Audit Telemetry Card */}
      <div className="bg-zinc-950 border border-zinc-800 rounded-lg p-4">
        <div className="flex items-center justify-between pb-2 mb-3 border-b border-zinc-800">
          <div className="flex items-center gap-2">
            <Activity className="w-3.5 h-3.5 text-indigo-400" />
            <span className="text-xs uppercase text-zinc-400 font-bold tracking-wider">
              Recent Price Feed Resolution Audit Log ({audit.length})
            </span>
          </div>
          <span className="text-[10px] text-emerald-400 font-bold">PRICING DAEMON ACTIVE</span>
        </div>

        <div className="divide-y divide-zinc-900 max-h-52 overflow-y-auto pr-1">
          {audit.length === 0 ? (
            <div className="py-4 text-center text-zinc-600 text-xs">No price feed resolution audit records yet.</div>
          ) : (
            audit.map((rec: PriceAuditRecord, idx: number) => (
              <div key={idx} className="py-2 px-1 flex items-center justify-between text-xs hover:bg-zinc-900/30 rounded">
                <div className="flex items-center gap-3">
                  <span className="font-bold text-zinc-200">{rec.symbol}/{rec.quote_currency}</span>
                  <span className="text-zinc-500 text-[11px]">{rec.provider_id}</span>
                  {rec.rate_numerator && rec.rate_denominator && (
                    <span className="text-zinc-400 text-[11px] font-mono">
                      Rate: {rec.rate_numerator}/{rec.rate_denominator}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-zinc-500 text-[10px]">{rec.created_at}</span>
                  <span className="text-zinc-400 text-[10px]">{rec.latency_ms}ms</span>
                  {getStatusBadge(rec.status)}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};
