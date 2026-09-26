import { FormEvent, useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import type { CapitalGainsSummary, DisposalPreview, OpenTaxLots, TaxTerm, UnrealizedGains } from '../types';

export function TaxPanel() {
  const [year, setYear] = useState(String(new Date().getFullYear()));
  const [term, setTerm] = useState<TaxTerm>('ALL');
  const [lots, setLots] = useState<OpenTaxLots | null>(null);
  const [gains, setGains] = useState<CapitalGainsSummary | null>(null);
  const [unrealized, setUnrealized] = useState<UnrealizedGains | null>(null);
  const [commodity, setCommodity] = useState('');
  const [account, setAccount] = useState('');
  const [quantity, setQuantity] = useState('');
  const [proceedsRate, setProceedsRate] = useState('');
  const [strategy, setStrategy] = useState<'FIFO' | 'LIFO' | 'HIFO'>('FIFO');
  const [disposalDate, setDisposalDate] = useState(new Date().toISOString().slice(0, 10));
  const [preview, setPreview] = useState<DisposalPreview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api.getCapitalGainsSummary({ tax_year: year, term }),
      api.getOpenTaxLots(),
      api.getUnrealizedGains(),
    ]).then(([summary, openLots, unrealizedSummary]) => {
      setGains(summary); setLots(openLots); setUnrealized(unrealizedSummary); setError(null);
    }).catch((err: Error) => setError(err.message));
  }, [year, term]);

  const choices = useMemo(() => lots?.lots ?? [], [lots]);
  useEffect(() => {
    if (!commodity && choices[0]) { setCommodity(choices[0].commodity); setAccount(choices[0].account); }
  }, [choices, commodity]);

  const submitPreview = async (event: FormEvent) => {
    event.preventDefault();
    try {
      setPreview(await api.previewLotDisposal({ commodity, account, quantity, proceeds_rate: proceedsRate, strategy, disposal_date: disposalDate }));
      setError(null);
    } catch (err) { setError(err instanceof Error ? err.message : 'Preview failed'); }
  };

  const money = (value: string | null | undefined, currency = gains?.functional_currency ?? 'USD') => `${value ?? '—'} ${currency}`;
  return <main className="flex-1 overflow-y-auto bg-[#0d0a08] p-6 space-y-5 font-mono">
    <header className="flex items-center justify-between border-b border-[#2c2420] pb-3">
      <div><h2 className="font-serif text-xl font-bold">Tax &amp; Gains</h2><p className="text-xs text-[#7a6e65]">Read-only Phase 14 lot analysis and disposal simulation</p></div>
      <a href="/api/analytics/gains/export?ledger_id=default" className="border border-[#c4501a] px-3 py-2 text-xs text-[#e2765f]">Export Form 8949 CSV</a>
    </header>
    {error && <div role="alert" className="border border-[#4a1c14] bg-[#2c120e] p-3 text-sm text-[#e2765f]">{error}</div>}

    <section className="space-y-3">
      <div className="flex gap-3 text-xs">
        <label>Tax year <input type="number" min="1000" max="9999" value={year} onChange={(e) => setYear(e.target.value)} className="ml-2 w-24 bg-[#1a1410] border border-[#3a2e26] p-1" /></label>
        <label>Term <select value={term} onChange={(e) => setTerm(e.target.value as TaxTerm)} className="ml-2 bg-[#1a1410] border border-[#3a2e26] p-1"><option>ALL</option><option>SHORT_TERM</option><option>LONG_TERM</option></select></label>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[['Realized gain/loss', gains?.total_realized_gain_display], ['Proceeds', gains?.total_proceeds_display], ['Cost basis', gains?.total_cost_basis_display], ['Disposals', String(gains?.disposal_count ?? 0)]].map(([label, value]) => <div key={label} className="border border-[#2c2420] bg-[#1a1410] p-4"><div className="text-[10px] uppercase text-[#7a6e65]">{label}</div><div className="mt-2 text-lg text-[#f2ece2]">{label === 'Disposals' ? value : money(value)}</div></div>)}
      </div>
    </section>

    <section className="space-y-2"><h3 className="text-xs uppercase text-[#b8922a]">Open tax lots</h3><div className="overflow-x-auto border border-[#2c2420]"><table className="w-full text-left text-xs"><thead className="bg-[#1a1410] text-[#b8922a]"><tr>{['Account','Commodity','Remaining units','Cost basis','Acquired'].map((h) => <th key={h} className="p-3">{h}</th>)}</tr></thead><tbody>{choices.map((lot) => <tr key={lot.lot_key} className="border-t border-[#2c2420]"><td className="p-3">{lot.account}</td><td className="p-3">{lot.commodity}</td><td className="p-3">{lot.quantity_display}</td><td className="p-3">{money(lot.current_basis_display, lot.functional_currency)}</td><td className="p-3">{lot.acquisition_date}</td></tr>)}</tbody></table></div></section>

    <section className="space-y-2"><h3 className="text-xs uppercase text-[#b8922a]">Unrealized gains</h3><div className="grid grid-cols-3 gap-3 text-xs"><div className="border border-[#2c2420] p-3">Basis<br />{money(unrealized?.total_cost_basis_display, unrealized?.functional_currency)}</div><div className="border border-[#2c2420] p-3">Market value<br />{money(unrealized?.total_market_value_display, unrealized?.functional_currency)}</div><div className="border border-[#2c2420] p-3">Gain/loss<br />{money(unrealized?.total_unrealized_gain_display, unrealized?.functional_currency)}</div></div><div className="text-xs text-[#a89e94]">{unrealized?.positions.map((position) => <div key={position.commodity} className="flex justify-between border-b border-[#2c2420] p-2"><span>{position.commodity} · {position.quantity_display}</span><span>{money(position.unrealized_gain_display, position.functional_currency)}</span></div>)}</div></section>

    <section className="border border-[#2c2420] bg-[#1a1410] p-4 space-y-3"><h3 className="text-xs uppercase text-[#b8922a]">Disposal preview · no writes</h3><form onSubmit={submitPreview} className="grid md:grid-cols-6 gap-3 text-xs"><label>Lot<select value={`${account}|${commodity}`} onChange={(e) => { const [nextAccount, nextCommodity] = e.target.value.split('|'); setAccount(nextAccount); setCommodity(nextCommodity); }} className="block w-full bg-[#0d0a08] border border-[#3a2e26] p-2">{choices.map((lot) => <option key={lot.lot_key} value={`${lot.account}|${lot.commodity}`}>{lot.commodity} · {lot.account}</option>)}</select></label><label>Quantity<input required inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} className="block w-full bg-[#0d0a08] border border-[#3a2e26] p-2" /></label><label>Sale price/unit<input required inputMode="decimal" value={proceedsRate} onChange={(e) => setProceedsRate(e.target.value)} className="block w-full bg-[#0d0a08] border border-[#3a2e26] p-2" /></label><label>Disposal date<input required type="date" value={disposalDate} onChange={(e) => setDisposalDate(e.target.value)} className="block w-full bg-[#0d0a08] border border-[#3a2e26] p-2" /></label><label>Strategy<select value={strategy} onChange={(e) => setStrategy(e.target.value as typeof strategy)} className="block w-full bg-[#0d0a08] border border-[#3a2e26] p-2"><option>FIFO</option><option>LIFO</option><option>HIFO</option></select></label><button disabled={!commodity || !quantity || !proceedsRate} className="self-end bg-[#c4501a] text-black font-bold p-2 disabled:opacity-40">Preview</button></form>{preview && <div className="grid grid-cols-3 gap-3 text-xs"><div>Estimated proceeds<br />{money(preview.total_proceeds_display)}</div><div>Estimated basis<br />{money(preview.total_cost_basis_display)}</div><div>Estimated gain/loss<br />{money(preview.total_realized_gain_display)}</div></div>}</section>
  </main>;
}
