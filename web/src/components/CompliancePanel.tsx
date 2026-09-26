import { ChangeEvent, FormEvent, useState } from 'react';
import { api } from '../api';
import type { ComplianceBundle, ComplianceBundleVerification, ComplianceFramework } from '../types';

const FRAMEWORKS: ComplianceFramework[] = ['SOC2_TYPE2', 'ISO27001', 'SOX', 'CUSTOM'];

export function CompliancePanel() {
  const [framework, setFramework] = useState<ComplianceFramework>('SOC2_TYPE2');
  const [periodStart, setPeriodStart] = useState(`${new Date().getFullYear()}-01-01T00:00:00Z`);
  const [periodEnd, setPeriodEnd] = useState(`${new Date().getFullYear()}-12-31T23:59:59Z`);
  const [bundle, setBundle] = useState<ComplianceBundle | null>(null);
  const [verifyFile, setVerifyFile] = useState<File | null>(null);
  const [verification, setVerification] = useState<ComplianceBundleVerification | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [verifying, setVerifying] = useState(false);

  const generate = async (event: FormEvent) => {
    event.preventDefault();
    setGenerating(true);
    try {
      setBundle(await api.generateComplianceBundle({ framework, period_start_utc: periodStart, period_end_utc: periodEnd }));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Bundle generation failed');
    } finally {
      setGenerating(false);
    }
  };

  const verify = async (event: FormEvent) => {
    event.preventDefault();
    if (!verifyFile) return;
    setVerifying(true);
    try {
      setVerification(await api.verifyComplianceBundle(verifyFile));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Bundle verification failed');
    } finally {
      setVerifying(false);
    }
  };

  const onFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    setVerifyFile(event.target.files?.[0] ?? null);
    setVerification(null);
  };

  return <main className="flex-1 overflow-y-auto bg-[#0d0a08] p-6 space-y-5 font-mono">
    <header className="border-b border-[#2c2420] pb-3">
      <h2 className="font-serif text-xl font-bold">Compliance bundles</h2>
      <p className="text-xs text-[#7a6e65]">Sealed, tamper-evident audit archives per framework and period</p>
    </header>
    {error && <div role="alert" className="border border-[#4a1c14] bg-[#2c120e] p-3 text-sm text-[#e2765f]">{error}</div>}

    <section className="border border-[#2c2420] bg-[#1a1410] p-4 space-y-3">
      <h3 className="text-xs uppercase text-[#b8922a]">Generate bundle</h3>
      <form onSubmit={generate} className="grid md:grid-cols-4 gap-3 text-xs">
        <label>Framework<select value={framework} onChange={(e) => setFramework(e.target.value as ComplianceFramework)} className="block w-full bg-[#0d0a08] border border-[#3a2e26] p-2">{FRAMEWORKS.map((f) => <option key={f} value={f}>{f}</option>)}</select></label>
        <label>Period start (UTC)<input required value={periodStart} onChange={(e) => setPeriodStart(e.target.value)} className="block w-full bg-[#0d0a08] border border-[#3a2e26] p-2" /></label>
        <label>Period end (UTC)<input required value={periodEnd} onChange={(e) => setPeriodEnd(e.target.value)} className="block w-full bg-[#0d0a08] border border-[#3a2e26] p-2" /></label>
        <button disabled={generating} className="self-end bg-[#c4501a] text-black font-bold p-2 disabled:opacity-40">{generating ? 'Generating…' : 'Generate'}</button>
      </form>
      {bundle && <div className="grid md:grid-cols-3 gap-3 text-xs pt-2 border-t border-[#2c2420]">
        <div>Bundle ID<br /><span className="text-[#f2ece2]">{bundle.bundle_id}</span></div>
        <div>Records<br /><span className="text-[#f2ece2]">{bundle.record_count}</span></div>
        <div>Merkle root<br /><span className="break-all text-[#f2ece2]">{bundle.merkle_root_hex}</span></div>
        <div className="md:col-span-3">SHA-256<br /><span className="break-all text-[#f2ece2]">{bundle.sealed_archive_sha256}</span></div>
      </div>}
    </section>

    <section className="border border-[#2c2420] bg-[#1a1410] p-4 space-y-3">
      <h3 className="text-xs uppercase text-[#b8922a]">Verify archive · read-only</h3>
      <form onSubmit={verify} className="flex items-end gap-3 text-xs">
        <label className="flex-1">Sealed archive (.tar)<input required type="file" accept=".tar" onChange={onFileChange} className="block w-full bg-[#0d0a08] border border-[#3a2e26] p-2" /></label>
        <button disabled={!verifyFile || verifying} className="bg-[#c4501a] text-black font-bold p-2 disabled:opacity-40">{verifying ? 'Verifying…' : 'Verify'}</button>
      </form>
      {verification && <div className="grid md:grid-cols-3 gap-3 text-xs pt-2 border-t border-[#2c2420]">
        <div>Status<br /><span className={verification.is_valid ? 'text-[#7fbf6a]' : 'text-[#e2765f]'}>{verification.is_valid ? 'VALID' : 'INVALID'}</span></div>
        <div>Bundle ID<br /><span className="text-[#f2ece2]">{verification.bundle_id}</span></div>
        <div>Records<br /><span className="text-[#f2ece2]">{verification.record_count}</span></div>
      </div>}
    </section>
  </main>;
}
