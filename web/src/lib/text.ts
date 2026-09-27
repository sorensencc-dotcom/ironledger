// Bank/broker feeds hand us shouty, all-caps memo text (e.g. "REDEMPTION FROM CORE
// ACCOUNT FIDELITY GOVERNMENT CASH RESERVES (FDRXX)"). Title-case it for display,
// leaving parenthetical codes/tickers (which are reliably wrapped in parens in this
// data) untouched rather than guessing which bare short words are acronyms.
export function humanizePayee(raw: string | null | undefined): string {
  if (!raw) return raw || '';
  return raw
    .split(' ')
    .map((word) => {
      if (/^\(.+\)$/.test(word)) return word;
      const lower = word.toLowerCase();
      return lower.charAt(0).toUpperCase() + lower.slice(1);
    })
    .join(' ');
}
