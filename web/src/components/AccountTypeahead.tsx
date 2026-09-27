import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { Rule } from '../types';
import { accountOptionsFromRules, filterAccountOptions } from './accountOptions';

interface AccountTypeaheadProps {
  value: string;
  onChange: (account: string) => void;
  rules: Rule[];
  placeholder?: string;
  disabled?: boolean;
}

const MENU_MARGIN = 4;
const MENU_MAX_HEIGHT = 192;

export const AccountTypeahead: React.FC<AccountTypeaheadProps> = ({
  value,
  onChange,
  rules,
  placeholder = 'Expenses:Groceries',
  disabled = false,
}) => {
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const [menuStyle, setMenuStyle] = useState<React.CSSProperties>({});
  const wrapRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const options = useMemo(() => accountOptionsFromRules(rules), [rules]);
  const filtered = useMemo(() => filterAccountOptions(options, value), [options, value]);
  const query = value.trim();
  const queryIsNew =
    query.includes(':') && !options.some((o) => o.account.toLowerCase() === query.toLowerCase());
  const rows = queryIsNew
    ? [{ account: query, patterns: ['new account'], isNew: true as const }, ...filtered.map((o) => ({ ...o, isNew: false as const }))]
    : filtered.map((o) => ({ ...o, isNew: false as const }));

  useEffect(() => {
    setHighlight(0);
  }, [value, open]);

  useEffect(() => {
    const onDoc = (ev: MouseEvent) => {
      const target = ev.target as HTMLElement;
      if (wrapRef.current?.contains(target)) return;
      if (target?.closest('[data-account-typeahead-menu]')) return;
      setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  // Render the suggestion list in a portal, positioned in fixed coordinates
  // against the input's own bounding box. AccountTypeahead is used both in a
  // tall side panel (room to open upward) and inline in a scrolling table
  // row (where opening upward can run out of room near the top of the
  // scroll area) — pick whichever side has more space instead of a fixed
  // direction, so the menu is never clipped by a scrollable ancestor.
  useLayoutEffect(() => {
    if (!open || !inputRef.current) return;
    const updatePosition = () => {
      if (!inputRef.current) return;
      const rect = inputRef.current.getBoundingClientRect();
      const spaceBelow = window.innerHeight - rect.bottom;
      const spaceAbove = rect.top;
      const openUp = spaceBelow < MENU_MAX_HEIGHT && spaceAbove > spaceBelow;
      setMenuStyle({
        position: 'fixed',
        left: rect.left,
        width: rect.width,
        maxHeight: Math.max(120, Math.min(MENU_MAX_HEIGHT, (openUp ? spaceAbove : spaceBelow) - MENU_MARGIN * 2)),
        ...(openUp
          ? { bottom: window.innerHeight - rect.top + MENU_MARGIN }
          : { top: rect.bottom + MENU_MARGIN }),
      });
    };
    updatePosition();
    const closeOnScroll = () => setOpen(false);
    window.addEventListener('scroll', closeOnScroll, true);
    window.addEventListener('resize', updatePosition);
    return () => {
      window.removeEventListener('scroll', closeOnScroll, true);
      window.removeEventListener('resize', updatePosition);
    };
  }, [open]);

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
        ref={inputRef}
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
        className="w-full px-3 py-2 rounded-[4px] bg-[#0d0a08] border border-[#3a2e26] text-[#f2ece2] text-xs font-mono focus:outline-none focus:border-[#c4501a] disabled:opacity-50"
      />
      {open && rows.length > 0 && createPortal(
        <ul
          role="listbox"
          data-account-typeahead-menu
          style={menuStyle}
          className="z-[9999] overflow-y-auto bg-[#1a1410] border border-[#3a2e26] shadow-xl rounded-[4px]"
        >
          <li className="sticky top-0 z-10 px-3 py-1.5 bg-[#241c16] border-b border-[#3a2e26] text-[10px] text-[#7a6e65] font-sans uppercase tracking-wider">
            {filtered.length} existing categor{filtered.length === 1 ? 'y' : 'ies'} · ↑↓ navigate · Enter select
          </li>
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
        </ul>,
        document.body,
      )}
    </div>
  );
};
