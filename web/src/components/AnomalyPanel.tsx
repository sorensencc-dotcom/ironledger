import { FormEvent, useEffect, useState } from 'react';
import { api } from '../api';
import type { AnomalyFlag, AnomalyResolution } from '../types';

const STATUS_FILTERS = ['ALL', 'OPEN', 'RESOLVED'] as const;
type StatusFilter = typeof STATUS_FILTERS[number];

export function AnomalyPanel() {
  const [flags, setFlags] = useState<AnomalyFlag[]>([]);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('OPEN');
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [resolution, setResolution] = useState<AnomalyResolution>('DISMISSED');
  const [reason, setReason] = useState('');

  const load = () => {
    api.getAnomalyFlags({ status: statusFilter === 'ALL' ? undefined : statusFilter })
      .then((data) => { setFlags(data.flags); setError(null); })
      .catch((err: Error) => setError(err.message));
  };

  useEffect(load, [statusFilter]);

  const scanNow = async () => {
    setScanning(true);
    try {
      await api.scanAnomalies();
      load();
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Scan failed');
    } finally {
      setScanning(false);
    }
  };

  const submitResolve = async (event: FormEvent, flagId: string) => {
    event.preventDefault();
    try {
      await api.resolveAnomalyFlag(flagId, { resolution_status: resolution, actor: 'operator', reason });
      setResolvingId(null);
      setReason('');
      load();
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Resolve failed');
    }
  };

  const score = (flag: AnomalyFlag) => `${flag.score_numerator}/${flag.score_denominator}`;

  return <main className="flex-1 overflow-y-auto bg-[#0d0a08] p-6 space-y-5 font-mono">
    <header className="flex items-center justify-between border-b border-[#2c2420] pb-3">
      <div><h2 className="font-serif text-xl font-bold">Anomaly flags</h2><p className="text-xs text-[#7a6e65]">Pure rational fraud &amp; anomaly detection findings</p></div>
      <button onClick={scanNow} disabled={scanning} className="bg-[#c4501a] text-black font-bold px-3 py-2 text-xs disabled:opacity-40">{scanning ? 'Scanning…' : 'Scan now'}</button>
    </header>
    {error && <div role="alert" className="border border-[#4a1c14] bg-[#2c120e] p-3 text-sm text-[#e2765f]">{error}</div>}

    <div className="flex gap-3 text-xs">
      {STATUS_FILTERS.map((s) => (
        <button key={s} onClick={() => setStatusFilter(s)} className={`border px-3 py-1 ${statusFilter === s ? 'border-[#c4501a] text-[#e2765f]' : 'border-[#2c2420] text-[#a89e94]'}`}>{s}</button>
      ))}
    </div>

    <section className="overflow-x-auto border border-[#2c2420]">
      <table className="w-full text-left text-xs">
        <thead className="bg-[#1a1410] text-[#b8922a]">
          <tr>{['Rule', 'Severity', 'Score', 'Status', 'Created', ''].map((h) => <th key={h} className="p-3">{h}</th>)}</tr>
        </thead>
        <tbody>
          {flags.map((flag) => <tr key={flag.flag_id} className="border-t border-[#2c2420] align-top">
            <td className="p-3">{flag.rule_type}</td>
            <td className="p-3">{flag.severity}</td>
            <td className="p-3">{score(flag)}</td>
            <td className="p-3">{flag.resolution_status ?? 'OPEN'}</td>
            <td className="p-3">{flag.created_at_utc}</td>
            <td className="p-3">
              {!flag.resolution_status && (resolvingId === flag.flag_id ? (
                <form onSubmit={(e) => submitResolve(e, flag.flag_id)} className="flex gap-2">
                  <select value={resolution} onChange={(e) => setResolution(e.target.value as AnomalyResolution)} className="bg-[#0d0a08] border border-[#3a2e26] p-1">
                    <option>DISMISSED</option><option>CONFIRMED_FRAUD</option><option>RESOLVED_VALID</option>
                  </select>
                  <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="reason" className="bg-[#0d0a08] border border-[#3a2e26] p-1" />
                  <button className="border border-[#c4501a] px-2 text-[#e2765f]">Save</button>
                </form>
              ) : (
                <button onClick={() => setResolvingId(flag.flag_id)} className="border border-[#2c2420] px-2 text-[#a89e94]">Resolve</button>
              ))}
            </td>
          </tr>)}
        </tbody>
      </table>
      {flags.length === 0 && <div className="p-4 text-xs text-[#7a6e65]">No anomaly flags for this filter.</div>}
    </section>
  </main>;
}
