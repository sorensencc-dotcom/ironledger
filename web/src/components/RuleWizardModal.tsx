import React, { useEffect, useState } from 'react';
import { X, Wand2, Check, AlertCircle } from 'lucide-react';
import { api } from '../api';
import type { StagedTransaction } from '../types';

interface RuleWizardModalProps {
  isOpen: boolean;
  onClose: () => void;
  transaction: StagedTransaction | null;
  onRuleCreated: () => void;
}

export const RuleWizardModal: React.FC<RuleWizardModalProps> = ({
  isOpen,
  onClose,
  transaction,
  onRuleCreated,
}) => {
  const [matchType, setMatchType] = useState<'exact' | 'prefix' | 'regex'>('exact');
  const [pattern, setPattern] = useState('');
  const [targetAccount, setTargetAccount] = useState('Expenses:Groceries');
  const [retroMatches, setRetroMatches] = useState<number | null>(null);
  const [loadingCandidate, setLoadingCandidate] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (transaction && isOpen) {
      setLoadingCandidate(true);
      setError(null);
      api.generateCandidate(transaction.staged_id, matchType)
        .then((res) => {
          setPattern(res.suggested_pattern);
          if (res.target_account && res.target_account !== 'Expenses:Unallocated') {
            setTargetAccount(res.target_account);
          }
          setRetroMatches(res.retroactive_matches);
        })
        .catch((err) => setError(err.message))
        .finally(() => setLoadingCandidate(false));
    }
  }, [transaction, isOpen, matchType]);

  if (!isOpen || !transaction) return null;

  const handleSaveRule = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.createRule({
        match_type: matchType,
        pattern,
        target_account: targetAccount,
        priority: matchType === 'exact' ? 50 : 100,
      });
      onRuleCreated();
      onClose();
    } catch (err: any) {
      setError(err.message || 'Failed to save rule');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="w-full max-w-lg bg-slate-900 border border-slate-700 rounded-lg shadow-2xl overflow-hidden font-sans">
        {/* Modal Header */}
        <div className="px-5 py-4 border-b border-slate-800 flex items-center justify-between bg-slate-850">
          <div className="flex items-center space-x-2">
            <Wand2 className="w-4 h-4 text-indigo-400" />
            <h3 className="font-semibold text-sm text-slate-100">Rule Creation Wizard</h3>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-200">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-5 space-y-4 text-xs font-mono">
          {error && (
            <div className="p-3 rounded bg-rose-950/60 border border-rose-800 text-rose-300 flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {/* Source Payee Info */}
          <div className="p-3 rounded bg-slate-800/50 border border-slate-700/50 space-y-1">
            <span className="text-slate-500 uppercase text-[10px]">Staged Payee</span>
            <div className="text-slate-200 font-bold truncate">{transaction.payee || '(Unnamed)'}</div>
          </div>

          {/* Match Type Picker */}
          <div className="space-y-1.5">
            <label className="text-slate-400 uppercase text-[10px]">Match Algorithm</label>
            <div className="grid grid-cols-3 gap-2">
              {(['exact', 'prefix', 'regex'] as const).map((type) => (
                <button
                  key={type}
                  type="button"
                  onClick={() => setMatchType(type)}
                  className={`py-1.5 px-3 rounded text-center uppercase font-bold border transition-colors ${
                    matchType === type
                      ? 'bg-indigo-600/30 text-indigo-300 border-indigo-500'
                      : 'bg-slate-800/60 text-slate-400 border-slate-700 hover:bg-slate-800'
                  }`}
                >
                  {type}
                </button>
              ))}
            </div>
          </div>

          {/* Pattern Input */}
          <div className="space-y-1.5">
            <label className="text-slate-400 uppercase text-[10px]">Matching Pattern</label>
            <input
              type="text"
              value={pattern}
              onChange={(e) => setPattern(e.target.value)}
              className="w-full px-3 py-2 rounded bg-slate-800 border border-slate-700 text-slate-200 text-xs focus:outline-none focus:border-indigo-500"
            />
          </div>

          {/* Target Account Input */}
          <div className="space-y-1.5">
            <label className="text-slate-400 uppercase text-[10px]">Target Contra Account</label>
            <input
              type="text"
              value={targetAccount}
              onChange={(e) => setTargetAccount(e.target.value)}
              placeholder="Expenses:Food:Groceries"
              className="w-full px-3 py-2 rounded bg-slate-800 border border-slate-700 text-slate-200 text-xs focus:outline-none focus:border-indigo-500"
            />
          </div>

          {/* Retroactive Match Estimation Pill */}
          <div className="p-3 rounded bg-indigo-950/30 border border-indigo-800/40 flex items-center justify-between text-indigo-300 text-[11px]">
            <span>Retroactive Staging Matches:</span>
            <span className="font-bold">
              {loadingCandidate ? 'Computing...' : `${retroMatches ?? 1} transactions`}
            </span>
          </div>
        </div>

        {/* Modal Footer */}
        <div className="px-5 py-3 border-t border-slate-800 bg-slate-850 flex justify-end space-x-2">
          <button
            onClick={onClose}
            className="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSaveRule}
            disabled={saving || !pattern || !targetAccount}
            className="px-4 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium flex items-center gap-1.5 shadow-sm transition-colors disabled:opacity-50"
          >
            {saving ? <Wand2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
            <span>Save & Apply Rule</span>
          </button>
        </div>
      </div>
    </div>
  );
};

