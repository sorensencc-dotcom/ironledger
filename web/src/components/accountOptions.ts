import type { Rule } from '../types';

export type AccountOption = {
  account: string;
  patterns: string[];
};

export function isRuleActive(rule: Rule): boolean {
  return rule.active !== false && rule.active !== 0;
}

export function accountOptionsFromRules(rules: Rule[]): AccountOption[] {
  const map = new Map<string, string[]>();
  for (const rule of rules) {
    if (!isRuleActive(rule)) continue;
    const account = (rule.target_account || '').trim();
    if (!account) continue;
    const patterns = map.get(account) ?? [];
    const pattern = (rule.pattern || '').trim();
    if (pattern && !patterns.includes(pattern)) {
      patterns.push(pattern);
    }
    map.set(account, patterns);
  }
  return [...map.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([account, patterns]) => ({ account, patterns }));
}

export function filterAccountOptions(options: AccountOption[], query: string): AccountOption[] {
  const q = query.trim().toLowerCase();
  if (!q) return options;
  return options.filter(
    (opt) =>
      opt.account.toLowerCase().includes(q) ||
      opt.patterns.some((p) => p.toLowerCase().includes(q)),
  );
}
