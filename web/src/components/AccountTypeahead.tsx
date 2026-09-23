import React, { useEffect, useMemo, useRef, useState } from 'react';
import type { Rule } from '../types';
import { accountOptionsFromRules, filterAccountOptions } from './accountOptions';

interface AccountTypeaheadProps {
  value: string;
  onChange: (account: string) => void;
  rules: Rule[];
  placeholder?: string;
  disabled?: boolean;
}

export const AccountTypeahead: React.FC<AccountTypeaheadProps> = ({
  value,
  onChange,
  rules,
  placeholder = 'Expenses:Groceries',
  disabled = false,
}) => {
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const wrapRef = useRef<HTMLDivElement>(null);

  const options = useMemo(() => accountOptionsFromRules(rules), [rules]);
  const filtered = useMemo(() => filterAccountOptions(options, value), [options, value]);
  const query = value.trim();
  const queryIsNew =
    query.length > 0 && !options.some((o) => o.account.toLowerCase() === query.toLowerCase());
  const rows = queryIsNew
    ? [{ account: query, patterns: ['new account'], isNew: true as const }, ...filtered.map((o) => ({ ...o, isNew: false as const }))]
    : filtered.map((o) => ({ ...o, isNew: false as const }));

  useEffect(() => {
    setHighlight(0);
  }, [value, open]);

  useEffect(() => {
    const onDoc = (ev: MouseEvent) => {
      if (!wrapRef.current?.contains(ev.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  const pick = (account: string) => {
    onChange(account);
    setOpen(false);
  };

  const onKeyDown = (ev: React.KeyboardEvent<HTMLInputElement>) => {
    if (ev.key === 'ArrowDown') {
      ev.preventDefault();
      setOpen(true);
      setHighlight((h) => Math.min(h + 1, Math.max(0, rows.length - 1)));
      return;
    }
    if (ev.key === 'ArrowUp') {
      ev.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
      return;
    }
    if (ev.key === 'Enter' && open && rows[highlight]) {
      ev.preventDefault();
      pick(rows[highlight].account);
      return;
    }
    if (ev.key === 'Escape') {
      setOpen(false);
    }
  };

  return (
    <div ref={wrapRef} className="relative">
      <input
        type="text"
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
        disabled={disabled}
        value={value}
        placeholder={placeholder}
        onFocus={() => setOpen(true)}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
        }}
        onKeyDown={onKeyDown}
        className="w-full px-3 py-2 rounded-none bg-[#0d0a08] border border-[#3a2e26] text-[#f2ece2] text-xs font-mono focus:outline-none focus:border-[#c4501a] disabled:opacity-50"
      />
      {open && rows.length > 0 && (
        <ul
          role="listbox"
          className="absolute z-30 mt-0.5 w-full max-h-48 overflow-y-auto bg-[#1a1410] border border-[#3a2e26] shadow-xl"
        >
          {rows.map((row, idx) => (
            <li key={`${row.account}-${idx}`}>
              <button
                type="button"
                role="option"
                aria-selected={idx === highlight}
                className={`w-full text-left px-3 py-1.5 font-mono text-[11px] ${
                  idx === highlight ? 'bg-[#2c1a14] text-[#f2ece2]' : 'text-[#e8dfd1] hover:bg-[#241c16]'
                }`}
                onMouseEnter={() => setHighlight(idx)}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => pick(row.account)}
              >
                <div className="truncate">{row.isNew ? `Use ${row.account}` : row.account}</div>
                {!row.isNew && row.patterns.length > 0 && (
                  <div className="truncate text-[10px] text-[#7a6e65]">{row.patterns.join(' · ')}</div>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};
