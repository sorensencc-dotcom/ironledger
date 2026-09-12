import React from "react";

export interface HoldingRecord {
  commodity: string;
  total_units: number;
  total_cost_basis_minor_units: number;
  market_value_minor_units: number;
  unrealized_gain_minor_units: number;
  base_currency: string;
}

export const HoldingsView: React.FC<{ holdings: HoldingRecord[] }> = ({
  holdings,
}) => {
  const totalPortfolioMarketValue = holdings.reduce(
    (sum, h) => sum + Math.max(0, h.market_value_minor_units ?? 0),
    0
  );

  return (
    <div className="bg-zinc-950 border border-zinc-800 rounded-lg p-4 font-mono">
      <div className="flex justify-between items-center pb-3 mb-3 border-b border-zinc-800">
        <span className="text-xs uppercase text-zinc-400 font-bold tracking-wider">
          Consolidated Portfolio
        </span>
        <span className="text-sm font-semibold text-zinc-100">
          Total Value: $
          {(totalPortfolioMarketValue / 100).toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
          })}
        </span>
      </div>

      <table className="w-full text-left text-xs">
        <thead className="text-zinc-500 border-b border-zinc-900">
          <tr>
            <th className="py-2">Commodity</th>
            <th className="py-2">Allocation</th>
            <th className="py-2 text-right">Units</th>
            <th className="py-2 text-right">Cost Basis</th>
            <th className="py-2 text-right">Market Value</th>
            <th className="py-2 text-right">Unrealized P&amp;L</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-900 text-zinc-300">
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
                className="hover:bg-zinc-900/50 transition-colors"
              >
                <td className="py-2.5 font-bold text-white">{h.commodity}</td>
                <td className="py-2.5">
                  <div className="flex items-center gap-2">
                    <div className="w-16 bg-zinc-800 h-1.5 rounded-full overflow-hidden">
                      <div
                        className="bg-blue-500 h-full transition-all duration-300"
                        style={{ width: `${weightPct}%` }}
                      />
                    </div>
                    <span className="text-zinc-400 text-[11px]">
                      {weightPct}%
                    </span>
                  </div>
                </td>
                <td className="py-2.5 text-right font-medium">
                  {h.total_units.toLocaleString()}
                </td>
                <td className="py-2.5 text-right text-zinc-400">
                  ${((h.total_cost_basis_minor_units ?? 0) / 100).toFixed(2)}
                </td>
                <td className="py-2.5 text-right font-medium text-zinc-100">
                  ${(mv / 100).toFixed(2)}
                </td>
                <td
                  className={`py-2.5 text-right font-semibold ${
                    isProfit ? "text-emerald-400" : "text-rose-400"
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
  );
};
