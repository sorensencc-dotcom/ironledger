import type { Posting, SplitProposal, StagedTransaction } from '../types';

// The categorization target is the "contra" posting (the non-imported leg the
// operator assigns) — the backend now tags each posting with its `role`, so
// prefer that. Fall back to the old heuristic (first Expenses/Income/Equity
// posting) for responses that predate the role field, but note that fallback
// silently misses valid Liabilities targets (e.g. a credit card payment).
export function getCategoryAccount(tx: Pick<StagedTransaction, 'category_account' | 'postings'>): string | undefined {
  if (tx.category_account) return tx.category_account;
  const contra = tx.postings.find((p: Posting) => p.role === 'contra');
  if (contra) return contra.account;
  return tx.postings.find(
    (p: Posting) => /^(Expenses|Income|Equity):/.test(p.account) && !p.account.endsWith(':Unassigned'),
  )?.account;
}

export function splitProposalLineTotal(proposal?: Pick<SplitProposal, 'lines'> | null): number | null {
  if (!proposal?.lines?.length) return null;
  return proposal.lines.reduce((sum, line) => sum + line.total_price_minor, 0);
}
