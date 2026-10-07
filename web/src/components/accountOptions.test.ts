import { describe, expect, it } from 'vitest';
import type { Rule } from '../types';
import { splitProposalLineTotal } from '../lib/staging';
import { accountOptionsFromRules, filterAccountOptions } from './accountOptions';

function rule(partial: Partial<Rule> & Pick<Rule, 'rule_id' | 'pattern' | 'target_account'>): Rule {
  return {
    match_type: 'exact',
    importing_account: null,
    priority: 50,
    active: 1,
    created_at_utc: '2026-09-15T00:00:00Z',
    disabled_at_utc: null,
    ...partial,
  };
}

describe('accountOptionsFromRules', () => {
  it('dedupes target accounts and keeps patterns', () => {
    const opts = accountOptionsFromRules([
      rule({ rule_id: 'a', pattern: 'aldi', target_account: 'Expenses:Groceries' }),
      rule({ rule_id: 'b', pattern: 'publix', target_account: 'Expenses:Groceries' }),
      rule({ rule_id: 'c', pattern: 'geico', target_account: 'Expenses:Insurance', active: 0 }),
    ]);
    expect(opts).toEqual([
      { account: 'Expenses:Groceries', patterns: ['aldi', 'publix'] },
    ]);
  });
});

describe('filterAccountOptions', () => {
  const opts = [
    { account: 'Expenses:Auto', patterns: ['auto detailing sol'] },
    { account: 'Expenses:Groceries', patterns: ['aldi', 'publix'] },
  ];

  it('filters by account substring', () => {
    expect(filterAccountOptions(opts, 'groc').map((o) => o.account)).toEqual(['Expenses:Groceries']);
  });

  it('filters by rule pattern', () => {
    expect(filterAccountOptions(opts, 'DETAILING').map((o) => o.account)).toEqual(['Expenses:Auto']);
  });

  it('returns all when query is empty', () => {
    expect(filterAccountOptions(opts, '  ')).toEqual(opts);
  });
});

describe('splitProposalLineTotal', () => {
  it('returns null when proposal lines are unavailable', () => {
    expect(splitProposalLineTotal({})).toBeNull();
  });

  it('sums proposal line minor units', () => {
    expect(splitProposalLineTotal({
      lines: [
        { line_index: 0, total_price_minor: 1200 },
        { line_index: 1, total_price_minor: 350 },
      ],
    })).toBe(1550);
  });
});
