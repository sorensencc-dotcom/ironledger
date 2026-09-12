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
    <div className="fixed inset-0 bg-black/75 backdrop-blur-md z-50 flex items-center justify-center p-4 select-none">
      <div className="w-full max-w-lg bg-[#1a1410] border border-[#3a2e26] rounded-none shadow-2xl overflow-hidden font-sans relative">
        {/* Ghost Watermark */}
        <div className="ghost-watermark text-[6rem] -top-8 -right-4 select-none pointer-events-none">
          RULES
        </div>

        {/* Modal Header */}
        <div className="px-5 py-3.5 border-b border-[#2c2420] flex items-center justify-between bg-[#241c16] relative z-10">
          <div className="flex items-center space-x-2">
            <Wand2 className="w-4 h-4 text-[#b8922a]" />
            <h3 className="font-serif font-bold text-sm text-[#f2ece2] tracking-wide">
              Rule Creation Wizard
            </h3>
          </div>
          <button onClick={onClose} className="text-[#7a6e65] hover:text-[#f2ece2] transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-5 space-y-4 text-xs font-mono relative z-10">
          {error && (
            <div className="p-3 rounded-none bg-[#2c120e] border border-[#4a1c14] text-[#e2765f] flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {/* Source Payee Info */}
          <div className="p-3 rounded-none bg-[#130f0c] border border-[#2c2420] space-y-1">
            <span className="text-[#7a6e65] uppercase font-sans font-bold tracking-wider text-[10px]">Staged Payee</span>
            <div className="text-[#f2ece2] font-serif font-bold text-sm truncate">{transaction.payee || '(Unnamed)'}</div>
          </div>

          {/* Match Type Picker */}
          <div className="space-y-1.5">
            <label className="text-[#a89e94] uppercase font-sans font-bold tracking-wider text-[10px]">Match Algorithm</label>
            <div className="grid grid-cols-3 gap-2">
              {(['exact', 'prefix', 'regex'] as const).map((type) => (
                <button
                  key={type}
                  type="button"
                  onClick={() => setMatchType(type)}
                  className={`py-1.5 px-3 rounded-none text-center uppercase font-mono font-bold border transition-colors ${
                    matchType === type
                      ? 'bg-[#2c1a14] text-[#e2765f] border-[#c4501a]'
                      : 'bg-[#241c16] text-[#7a6e65] border-[#2c2420] hover:bg-[#2c2420] hover:text-[#e8dfd1]'
                  }`}
                >
                  {type}
                </button>
              ))}
            </div>
          </div>

          {/* Pattern Input */}
          <div className="space-y-1.5">
            <label className="text-[#a89e94] uppercase font-sans font-bold tracking-wider text-[10px]">Matching Pattern</label>
            <input
              type="text"
              value={pattern}
              onChange={(e) => setPattern(e.target.value)}
              className="w-full px-3 py-2 rounded-none bg-[#0d0a08] border border-[#3a2e26] text-[#f2ece2] text-xs font-mono focus:outline-none focus:border-[#c4501a]"
            />
          </div>

          {/* Target Account Input */}
          <div className="space-y-1.5">
            <label className="text-[#a89e94] uppercase font-sans font-bold tracking-wider text-[10px]">Target Contra Account</label>
            <input
              type="text"
              value={targetAccount}
              onChange={(e) => setTargetAccount(e.target.value)}
              placeholder="Expenses:Food:Groceries"
              className="w-full px-3 py-2 rounded-none bg-[#0d0a08] border border-[#3a2e26] text-[#f2ece2] text-xs font-mono focus:outline-none focus:border-[#c4501a]"
            />
          </div>

          {/* Retroactive Match Estimation Pill */}
          <div className="p-3 rounded-none bg-[#241c16] border border-[#3a2e26] flex items-center justify-between text-[#b8922a] text-[11px]">
            <span className="font-sans font-bold uppercase tracking-wider text-[10px]">Retroactive Staging Matches:</span>
            <span className="font-mono font-bold">
              {loadingCandidate ? 'Computing...' : `${retroMatches ?? 1} transactions`}
            </span>
          </div>
        </div>

        {/* Modal Footer */}
        <div className="px-5 py-3 border-t border-[#2c2420] bg-[#241c16] flex justify-end space-x-2 relative z-10">
          <button
            onClick={onClose}
            className="px-3.5 py-1.5 rounded-none bg-[#1a1410] hover:bg-[#2c2420] border border-[#3a2e26] text-[#a89e94] hover:text-[#f2ece2] text-xs font-mono uppercase tracking-wider transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSaveRule}
            disabled={saving || !pattern || !targetAccount}
            className="px-4 py-1.5 rounded-none bg-[#c4501a] hover:bg-[#d4622b] text-[#f2ece2] text-xs font-mono uppercase tracking-wider font-bold flex items-center gap-1.5 shadow-sm transition-colors disabled:opacity-50"
          >
            {saving ? <Wand2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
            <span>Save & Apply Rule</span>
          </button>
        </div>
      </div>
    </div>
  );
};

