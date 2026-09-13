import { useEffect, useState } from 'react';

type Allocation = {
  id: number; account: string; commodity: string; disposal_date: string;
  acquisition_date: string; units_disposed_minor: number; unit_scale: number;
  holding_period_days: number; term_classification: string;
  functional_proceeds_minor: number; functional_cost_basis_minor: number;
  functional_realized_gain_minor: number; strategy_applied: string;
};
type Gains = { functional_currency: string; summary: Record<string, number>; allocations: Allocation[] };

export function CapitalGainsLedger() {
  const [data, setData] = useState<Gains | null>(null);
  const [term, setTerm] = useState('ALL');
  const [year, setYear] = useState(new Date().getFullYear().toString());
  const load = () => fetch(`/api/analytics/gains?ledger_id=default&year=${year}&term=${term}`).then((r) => r.ok ? r.json() : Promise.reject(r.status)).then(setData).catch(() => setData(null));
  useEffect(() => { void load(); }, [year, term]);
  const money = (n: number) => `${(n / 100).toFixed(2)} ${data?.functional_currency ?? 'USD'}`;
  const exportCsv = () => { window.location.href = '/api/analytics/gains/export?ledger_id=default'; };
  return <main className="flex-1 overflow-y-auto bg-[#0d0a08] p-6 space-y-5 font-mono">
    <div className="flex items-center justify-between border-b border-[#2c2420] pb-3"><div><h2 className="font-serif text-xl font-bold">Tax &amp; Capital Gains</h2><p className="text-xs text-[#7a6e65]">Deterministic lot disposal ledger</p></div><button onClick={exportCsv} className="border border-[#c4501a] px-3 py-2 text-xs text-[#e2765f]">Export Form 8949 CSV</button></div>
    <div className="flex gap-3 text-xs"><label>Tax year <input value={year} onChange={(e) => setYear(e.target.value)} className="ml-2 w-20 bg-[#1a1410] border border-[#3a2e26] p-1" /></label><label>Term <select value={term} onChange={(e) => setTerm(e.target.value)} className="ml-2 bg-[#1a1410] border border-[#3a2e26] p-1"><option>ALL</option><option>SHORT_TERM</option><option>LONG_TERM</option></select></label></div>
    {!data ? <div className="border border-[#4a1c14] p-6 text-sm text-[#e2765f]">Unable to load gains projection.</div> : <><div className="grid grid-cols-2 md:grid-cols-4 gap-3">{[['Net gain/loss','total_realized_gain_minor'],['Proceeds','total_proceeds_minor'],['Cost basis','total_cost_basis_minor']].map(([label, key]) => <div key={key} className="border border-[#2c2420] bg-[#1a1410] p-4"><div className="text-[10px] uppercase text-[#7a6e65]">{label}</div><div className="mt-2 text-lg text-[#f2ece2]">{money(data.summary[key] ?? 0)}</div></div>)}</div><div className="overflow-x-auto border border-[#2c2420]"><table className="w-full text-left text-xs"><thead className="bg-[#1a1410] text-[#b8922a]"><tr>{['Commodity','Acquired','Sold','Units','Term','Basis','Proceeds','Gain/Loss'].map((h) => <th key={h} className="p-3">{h}</th>)}</tr></thead><tbody>{data.allocations.map((a) => <tr key={a.id} className="border-t border-[#2c2420]"><td className="p-3">{a.commodity}</td><td className="p-3">{a.acquisition_date}</td><td className="p-3">{a.disposal_date}</td><td className="p-3">{a.units_disposed_minor / 10 ** a.unit_scale}</td><td className="p-3">{a.term_classification}</td><td className="p-3">{money(a.functional_cost_basis_minor)}</td><td className="p-3">{money(a.functional_proceeds_minor)}</td><td className={a.functional_realized_gain_minor >= 0 ? 'p-3 text-[#8fc79e]' : 'p-3 text-[#e2765f]'}>{money(a.functional_realized_gain_minor)}</td></tr>)}</tbody></table></div></>}
  </main>;
}
