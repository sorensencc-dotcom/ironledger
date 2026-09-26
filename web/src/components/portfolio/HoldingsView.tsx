import React from "react";
import type { StagedPortfolioSummary } from "../../types";

export interface HoldingRecord {
  commodity: string;
  total_units: number;
  total_cost_basis_minor_units: number;
  market_value_minor_units: number;
  unrealized_gain_minor_units: number;
  base_currency: string;
}

export const HoldingsView: React.FC<{ holdings: HoldingRecord[]; stagedSummary?: StagedPortfolioSummary | null }> = ({
  holdings,
  stagedSummary,
}) => {
  const totalPortfolioMarketValue = holdings.reduce(
    (sum, h) => sum + Math.max(0, h.market_value_minor_units ?? 0),
    0
  );

  return (
    <div className="bg-[#1a1410] border border-[#2c2420] rounded-none p-4 font-mono relative overflow-hidden">
      <div className="ghost-watermark text-[5rem] top-3 right-3 select-none pointer-events-none">
        HOLDINGS
      </div>

      <div className="flex justify-between items-center pb-3 mb-3 border-b border-[#2c2420] relative z-10">
        <span className="text-xs uppercase text-[#b8922a] font-sans font-bold tracking-wider">
          Consolidated Portfolio
        </span>
        <span className="text-sm font-semibold text-[#f2ece2]">
          Total Value: $
          {(totalPortfolioMarketValue / 100).toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
          })}
        </span>
      </div>

      <div className="overflow-x-auto relative z-10">
        {holdings.length === 0 && (stagedSummary?.staged_transaction_count ?? 0) > 0 && (
          <div className="mb-3 border border-[#3a2e26] bg-[#241c16] px-3 py-2 text-xs text-[#e0a84c]">
            {stagedSummary?.staged_transaction_count.toLocaleString()} staged transactions are available for review;
            confirmed investment holdings will appear here after approval.
          </div>
        )}
        {(stagedSummary?.candidates?.length ?? 0) > 0 && (
          <div className="mb-4 border border-[#2c2420] bg-[#130f0c] p-3">
            <div className="mb-2 text-[10px] font-bold uppercase tracking-wider text-[#b8922a]">Investment candidates</div>
            <div className="max-h-64 overflow-y-auto">
              {stagedSummary!.candidates.slice(0, 20).map((candidate, index) => (
                <div key={`${candidate.date}-${candidate.payee}-${index}`} className="flex items-center justify-between gap-3 border-t border-[#2c2420] py-2 text-[11px]">
                  <div className="min-w-0">
                    <div className="truncate text-[#f2ece2]">{candidate.payee || 'Unnamed transaction'}</div>
                    <div className="text-[#7a6e65]">{candidate.date} · {candidate.account}</div>
                  </div>
                  <div className="shrink-0 text-[#a89e94]">{(candidate.minor_units / 10 ** candidate.minor_unit_scale).toFixed(2)} {candidate.currency}</div>
                </div>
              ))}
            </div>
          </div>
        )}
        <table className="w-full text-left text-xs">
          <thead className="text-[#7a6e65] font-sans font-bold text-[10px] uppercase tracking-wider border-b border-[#2c2420]">
            <tr>
              <th className="py-2">Commodity</th>
              <th className="py-2">Allocation</th>
              <th className="py-2 text-right">Units</th>
              <th className="py-2 text-right">Cost Basis</th>
              <th className="py-2 text-right">Market Value</th>
              <th className="py-2 text-right">Unrealized P&amp;L</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#2c2420]/60 text-[#a89e94]">
            {holdings.length === 0 && (
              <tr><td colSpan={6} className="py-8 text-center text-[#7a6e65]">No confirmed investment holdings yet.</td></tr>
            )}
            {holdings.map((h) => {
              const mv = Math.max(0, h.market_value_minor_units ?? 0);
              const weightPct =
                totalPortfolioMarketValue > 0
                  ? ((mv / totalPortfolioMarketValue) * 100).toFixed(1)
                  : "0.0";
              const pnl = h.unrealized_gain_minor_units ?? 0;
              const isProfit = pnl >= 0;

              return (
                <tr
                  key={`${h.commodity}-${h.base_currency}`}
                  className="hover:bg-[#241c16]/60 transition-colors"
                >
                  <td className="py-2.5 font-bold text-[#f2ece2]">{h.commodity}</td>
                  <td className="py-2.5">
                    <div className="flex items-center gap-2">
                      <div className="w-16 bg-[#241c16] h-1.5 rounded-none overflow-hidden">
                        <div
                          className="bg-[#b8922a] h-full transition-all duration-300"
                          style={{ width: `${weightPct}%` }}
                        />
                      </div>
                      <span className="text-[#7a6e65] text-[11px]">
                        {weightPct}%
                      </span>
                    </div>
                  </td>
                  <td className="py-2.5 text-right font-medium">
                    {h.total_units.toLocaleString()}
                  </td>
                  <td className="py-2.5 text-right text-[#7a6e65]">
                    ${((h.total_cost_basis_minor_units ?? 0) / 100).toFixed(2)}
                  </td>
                  <td className="py-2.5 text-right font-medium text-[#f2ece2]">
                    ${(mv / 100).toFixed(2)}
                  </td>
                  <td
                    className={`py-2.5 text-right font-semibold ${
                      isProfit ? "text-[#8fc79e]" : "text-[#e2765f]"
                    }`}
                  >
                    {isProfit ? "+" : ""}
                    ${(pnl / 100).toFixed(2)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};
