import React, { useState } from 'react';
import { RefreshCw, Plus, Activity, CheckCircle2, AlertTriangle, XCircle, ArrowUpDown, Trash2, Lock, Unlock, TrendingUp, TrendingDown, Minus } from 'lucide-react';
import type { WatchlistData, WatchlistItem, PriceAuditRecord } from '../../types';

interface WatchlistPanelProps {
  data: WatchlistData | null;
  loading: boolean;
  onSync: () => Promise<void>;
  onAddSymbol: (symbol: string, quoteCurrency: string, manualQuote?: string) => Promise<void>;
  onRemoveSymbol: (symbol: string, quoteCurrency: string) => Promise<void>;
}

export const WatchlistPanel: React.FC<WatchlistPanelProps> = ({
  data,
  loading,
  onSync,
  onAddSymbol,
  onRemoveSymbol,
}) => {
  const [isLocked, setIsLocked] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [isAdding, setIsAdding] = useState(false);
  const [removingSymbol, setRemovingSymbol] = useState<string | null>(null);
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
    if (isLocked) return;
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

  const handleRemove = async (symbol: string, quoteCurrency: string) => {
    if (isLocked) return;
    try {
      setRemovingSymbol(`${symbol}-${quoteCurrency}`);
      await onRemoveSymbol(symbol, quoteCurrency);
    } finally {
      setRemovingSymbol(null);
    }
  };

  const getTrendBadge = (trend?: 'UP' | 'DOWN' | 'FLAT' | null, changePercent?: string | null, prevPrice?: string | null) => {
    if (!trend || trend === 'FLAT' || !changePercent) {
      return (
        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-none text-[10px] font-mono bg-[#130f0c] text-[#7a6e65] border border-[#2c2420]">
          <Minus className="w-2.5 h-2.5 text-[#7a6e65]" />
          <span>0.00%</span>
        </span>
      );
    }
    if (trend === 'UP') {
      return (
        <span
          title={prevPrice ? `Prior: $${prevPrice}` : undefined}
          className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-none text-[10px] font-mono font-bold bg-[#132a1c] text-[#8fc79e] border border-[#1d442b]"
        >
          <TrendingUp className="w-2.5 h-2.5 text-[#8fc79e]" />
          <span>{changePercent}</span>
        </span>
      );
    }
    return (
      <span
        title={prevPrice ? `Prior: $${prevPrice}` : undefined}
        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-none text-[10px] font-mono font-bold bg-[#2c120e] text-[#e2765f] border border-[#4a1c14]"
      >
        <TrendingDown className="w-2.5 h-2.5 text-[#e2765f]" />
        <span>{changePercent}</span>
      </span>
    );
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'SUCCESS':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-none text-[10px] font-bold bg-[#132a1c] text-[#8fc79e] border border-[#1d442b]">
            <CheckCircle2 className="w-3 h-3 text-[#8fc79e]" />
            SUCCESS
          </span>
        );
      case 'RECIPROCAL_SUCCESS':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-none text-[10px] font-bold bg-[#241c16] text-[#b8922a] border border-[#3a2e26]">
            <ArrowUpDown className="w-3 h-3 text-[#b8922a]" />
            RECIPROCAL
          </span>
        );
      case 'CIRCUIT_OPEN':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-none text-[10px] font-bold bg-[#2c120e] text-[#e2765f] border border-[#4a1c14] animate-pulse">
            <XCircle className="w-3 h-3 text-[#e2765f]" />
            CIRCUIT OPEN
          </span>
        );
      case 'STALE_CACHED':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-none text-[10px] font-bold bg-[#2a1d0d] text-[#e0a84c] border border-[#4a3518]">
            <AlertTriangle className="w-3 h-3 text-[#e0a84c]" />
            STALE
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-none text-[10px] font-bold bg-[#1a1410] text-[#a89e94] border border-[#2c2420]">
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
      <div className="bg-[#1a1410] border border-[#2c2420] rounded-none p-4 relative overflow-hidden">
        <div className="ghost-watermark text-[5rem] -top-6 -right-4 select-none pointer-events-none">
          WATCHLIST
        </div>

        <div className="flex flex-col sm:flex-row justify-between sm:items-center gap-3 pb-3 mb-3 border-b border-[#2c2420] relative z-10">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs uppercase text-[#b8922a] font-sans font-bold tracking-wider">
                Active Price Watchlist
              </span>
              <span className="text-[10px] px-2 py-0.2 rounded-none bg-[#241c16] text-[#b8922a] border border-[#3a2e26] font-bold">
                {items.length} PAIRS
              </span>
              {isLocked ? (
                <span className="text-[10px] px-2 py-0.2 rounded-none bg-[#241c16] text-[#b8922a] border border-[#3a2e26] font-bold flex items-center gap-1">
                  <Lock className="w-2.5 h-2.5" />
                  PROTECTED
                </span>
              ) : (
                <span className="text-[10px] px-2 py-0.2 rounded-none bg-[#132a1c] text-[#8fc79e] border border-[#1d442b] font-bold flex items-center gap-1 animate-pulse">
                  <Unlock className="w-2.5 h-2.5" />
                  EDIT MODE
                </span>
              )}
            </div>
            <p className="text-[11px] text-[#7a6e65] mt-0.5">
              Exact-rational market price resolution with dual Beancount &amp; SQLite persistence
            </p>
          </div>
          <div className="flex items-center gap-2">
            {/* Lock / Unlock Hammer Guard Button */}
            <button
              onClick={() => {
                const nextState = !isLocked;
                setIsLocked(nextState);
                if (nextState) setIsAdding(false);
              }}
              className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-none text-xs font-semibold border transition-all ${
                isLocked
                  ? 'bg-[#241c16] hover:bg-[#2c2420] text-[#b8922a] border-[#3a2e26]'
                  : 'bg-[#132a1c] hover:bg-[#1d442b] text-[#8fc79e] border-[#1d442b]'
              }`}
              title={isLocked ? 'Watchlist editing is locked. Click to unlock modifications.' : 'Watchlist editing is unlocked. Click to lock and prevent accidental edits.'}
            >
              {isLocked ? (
                <>
                  <Lock className="w-3.5 h-3.5 text-[#b8922a]" />
                  <span className="font-mono text-xs uppercase">Lock Guard</span>
                </>
              ) : (
                <>
                  <Unlock className="w-3.5 h-3.5 text-[#8fc79e]" />
                  <span className="font-mono text-xs uppercase">Unlocked</span>
                </>
              )}
            </button>

            <button
              onClick={() => {
                if (isLocked) {
                  setIsLocked(false);
                  setIsAdding(true);
                } else {
                  setIsAdding(!isAdding);
                }
              }}
              disabled={isLocked}
              title={isLocked ? 'Watchlist is locked. Click Lock Guard to unlock and add symbols.' : 'Add new target pair to watchlist'}
              className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-none text-xs font-mono uppercase transition-colors ${
                isLocked
                  ? 'bg-[#130f0c] text-[#7a6e65] border border-[#2c2420] cursor-not-allowed'
                  : 'bg-[#241c16] hover:bg-[#2c2420] text-[#e8dfd1] border border-[#3a2e26]'
              }`}
            >
              <Plus className="w-3.5 h-3.5 text-[#b8922a]" />
              <span>Add Symbol</span>
            </button>

            <button
              onClick={handleSync}
              disabled={syncing || loading}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-none text-xs font-mono uppercase font-bold bg-[#c4501a] hover:bg-[#d4622b] text-[#f2ece2] transition-all shadow-sm ${
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
          <form onSubmit={handleAddSubmit} className="mb-4 p-3 bg-[#130f0c] border border-[#3a2e26] rounded-none space-y-3 relative z-10">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-[#f2ece2] font-sans uppercase tracking-wider">Add Watchlist Target Pair</span>
              {addingError && <span className="text-xs text-[#e2765f]">{addingError}</span>}
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
              <div>
                <label className="text-[10px] text-[#7a6e65] uppercase font-sans font-bold block mb-1">Base Commodity (e.g. NVDA, SOL)</label>
                <input
                  type="text"
                  placeholder="AAPL"
                  value={newSymbol}
                  onChange={(e) => setNewSymbol(e.target.value)}
                  className="w-full bg-[#0d0a08] border border-[#3a2e26] rounded-none px-2.5 py-1.5 text-xs text-[#f2ece2] uppercase font-mono focus:outline-none focus:border-[#c4501a]"
                  required
                />
              </div>
              <div>
                <label className="text-[10px] text-[#7a6e65] uppercase font-sans font-bold block mb-1">Quote Currency</label>
                <input
                  type="text"
                  placeholder="USD"
                  value={newQuote}
                  onChange={(e) => setNewQuote(e.target.value)}
                  className="w-full bg-[#0d0a08] border border-[#3a2e26] rounded-none px-2.5 py-1.5 text-xs text-[#f2ece2] uppercase font-mono focus:outline-none focus:border-[#c4501a]"
                />
              </div>
              <div>
                <label className="text-[10px] text-[#7a6e65] uppercase font-sans font-bold block mb-1">Fallback Quote ($)</label>
                <input
                  type="text"
                  placeholder="225.50 (optional)"
                  value={newManualQuote}
                  onChange={(e) => setNewManualQuote(e.target.value)}
                  className="w-full bg-[#0d0a08] border border-[#3a2e26] rounded-none px-2.5 py-1.5 text-xs text-[#f2ece2] font-mono focus:outline-none focus:border-[#c4501a]"
                />
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={() => setIsAdding(false)}
                className="px-2.5 py-1 rounded-none text-xs bg-[#1a1410] border border-[#3a2e26] text-[#7a6e65] hover:text-[#f2ece2] font-mono uppercase"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="px-3 py-1 rounded-none text-xs bg-[#c4501a] hover:bg-[#d4622b] text-[#f2ece2] font-mono uppercase font-bold"
              >
                Save Symbol
              </button>
            </div>
          </form>
        )}

        {/* Watchlist Table */}
        <div className="overflow-x-auto relative z-10">
          <table className="w-full text-left text-xs">
            <thead className="text-[#7a6e65] font-sans font-bold text-[10px] uppercase tracking-wider border-b border-[#2c2420]">
              <tr>
                <th className="py-2">Symbol</th>
                <th className="py-2">Quote</th>
                <th className="py-2 text-right">Latest Price</th>
                <th className="py-2 text-center">Trend (24h)</th>
                <th className="py-2 text-right">Rational (N/D)</th>
                <th className="py-2 text-center">Provider</th>
                <th className="py-2 text-center">Status</th>
                <th className="py-2 text-right">Latency</th>
                <th className="py-2 text-right">As Of Date</th>
                <th className="py-2 text-center w-12">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#2c2420]/60 text-[#a89e94]">
              {items.length === 0 ? (
                <tr>
                  <td colSpan={10} className="py-6 text-center text-[#7a6e65]">
                    No watchlist symbols configured in config/prices.json.
                  </td>
                </tr>
              ) : (
                items.map((item: WatchlistItem) => (
                  <tr key={`${item.symbol}-${item.quote_currency}`} className="hover:bg-[#241c16]/60 transition-colors">
                    <td className="py-2.5 font-bold text-[#f2ece2] flex items-center gap-1.5">
                      <span className="w-1.5 h-1.5 bg-[#b8922a]"></span>
                      {item.symbol}
                    </td>
                    <td className="py-2.5 text-[#7a6e65]">{item.quote_currency}</td>
                    <td className="py-2.5 text-right font-bold text-[#f2ece2]">
                      {item.price_display ? `$${item.price_display}` : <span className="text-[#7a6e65]">—</span>}
                    </td>
                    <td className="py-2.5 text-center">
                      {getTrendBadge(item.trend, item.change_percent, item.previous_price_display)}
                    </td>
                    <td className="py-2.5 text-right text-[#a89e94] font-mono text-[11px]">
                      {item.rate_numerator && item.rate_denominator ? (
                        <span className="bg-[#0d0a08] px-1.5 py-0.5 rounded-none border border-[#2c2420]">
                          {item.rate_numerator}/{item.rate_denominator}
                        </span>
                      ) : (
                        <span className="text-[#7a6e65]">—</span>
                      )}
                    </td>
                    <td className="py-2.5 text-center text-[#a89e94]">
                      <span className="text-[11px] px-1.5 py-0.5 rounded-none bg-[#0d0a08] border border-[#2c2420]">
                        {item.last_provider}
                      </span>
                    </td>
                    <td className="py-2.5 text-center">{getStatusBadge(item.last_status)}</td>
                    <td className="py-2.5 text-right text-[#7a6e65]">
                      {item.last_latency_ms != null ? `${item.last_latency_ms}ms` : '0ms'}
                    </td>
                    <td className="py-2.5 text-right text-[#7a6e65] text-[11px]">
                      {item.directive_date || (item.updated_at ? item.updated_at.slice(0, 10) : '—')}
                    </td>

                    <td className="py-2.5 text-center">
                      {isLocked ? (
                        <span
                          title="Watchlist is locked. Unlock to delete symbols."
                          className="inline-flex p-1 text-[#7a6e65] cursor-not-allowed"
                        >
                          <Lock className="w-3.5 h-3.5 text-[#7a6e65]" />
                        </span>
                      ) : (
                        <button
                          onClick={() => handleRemove(item.symbol, item.quote_currency)}
                          disabled={removingSymbol === `${item.symbol}-${item.quote_currency}`}
                          title={`Remove ${item.symbol} from watchlist`}
                          className="p-1 rounded-none text-[#7a6e65] hover:text-[#e2765f] hover:bg-[#2c120e] transition-colors disabled:opacity-50"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Resolution Audit Telemetry Card */}
      <div className="bg-[#1a1410] border border-[#2c2420] rounded-none p-4 relative overflow-hidden">
        <div className="ghost-watermark text-[5rem] -top-6 -right-4 select-none pointer-events-none">
          AUDIT
        </div>

        <div className="flex items-center justify-between pb-2 mb-3 border-b border-[#2c2420] relative z-10">
          <div className="flex items-center gap-2">
            <Activity className="w-3.5 h-3.5 text-[#b8922a]" />
            <span className="text-xs uppercase text-[#b8922a] font-sans font-bold tracking-wider">
              Recent Price Feed Resolution Audit Log ({audit.length})
            </span>
          </div>
          <span className="text-[10px] text-[#8fc79e] font-bold font-sans uppercase tracking-wider">PRICING DAEMON ACTIVE</span>
        </div>

        <div className="divide-y divide-[#2c2420]/60 max-h-52 overflow-y-auto pr-1 relative z-10">
          {audit.length === 0 ? (
            <div className="py-4 text-center text-[#7a6e65] text-xs">No price feed resolution audit records yet.</div>
          ) : (
            audit.map((rec: PriceAuditRecord, idx: number) => (
              <div key={idx} className="py-2 px-1 flex items-center justify-between text-xs hover:bg-[#241c16]/60 rounded-none">
                <div className="flex items-center gap-3">
                  <span className="font-bold text-[#f2ece2]">{rec.symbol}/{rec.quote_currency}</span>
                  <span className="text-[#7a6e65] text-[11px]">{rec.provider_id}</span>
                  {rec.rate_numerator && rec.rate_denominator && (
                    <span className="text-[#a89e94] text-[11px] font-mono">
                      Rate: {rec.rate_numerator}/{rec.rate_denominator}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-[#7a6e65] text-[10px]">{rec.created_at}</span>
                  <span className="text-[#a89e94] text-[10px]">{rec.latency_ms}ms</span>
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
