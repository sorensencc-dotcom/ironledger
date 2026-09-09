import type {
  AuditEvent,
  BalanceItem,
  CompileResult,
  FreshnessStatus,
  MutationEvent,
  Posting,
  Rule,
  RuleDrift,
  SafeModeStatus,
  StagedTransaction,
} from './types';

const API_BASE = '/api';

export const api = {
  // Staging
  async getStaging(status?: string): Promise<StagedTransaction[]> {
    const url = status ? `${API_BASE}/staging?status=${status}` : `${API_BASE}/staging`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Failed to fetch staging: ${res.statusText}`);
    return res.json();
  },

  async categorize(stagedId: string, targetAccount: string, notes?: string) {
    const res = await fetch(`${API_BASE}/staging/${stagedId}/categorize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target_account: targetAccount, notes }),
    });
    if (!res.ok) throw new Error(`Failed to categorize: ${res.statusText}`);
    return res.json();
  },

  async approve(stagedId: string, targetAccount?: string) {
    const res = await fetch(`${API_BASE}/staging/${stagedId}/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(targetAccount ? { target_account: targetAccount } : {}),
    });
    if (!res.ok) throw new Error(`Failed to approve: ${res.statusText}`);
    return res.json();
  },

  async reject(stagedId: string, reason?: string) {
    const res = await fetch(`${API_BASE}/staging/${stagedId}/reject`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    });
    if (!res.ok) throw new Error(`Failed to reject: ${res.statusText}`);
    return res.json();
  },

  async split(stagedId: string, postings: Posting[]) {
    const res = await fetch(`${API_BASE}/staging/${stagedId}/split`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ postings }),
    });
    if (!res.ok) throw new Error(`Failed to split: ${res.statusText}`);
    return res.json();
  },

  // Rules
  async getRules(): Promise<Rule[]> {
    const res = await fetch(`${API_BASE}/rules`);
    if (!res.ok) throw new Error(`Failed to fetch rules: ${res.statusText}`);
    return res.json();
  },

  async createRule(payload: {
    match_type: 'exact' | 'prefix' | 'regex';
    pattern: string;
    target_account: string;
    importing_account?: string | null;
    priority?: number;
  }) {
    const res = await fetch(`${API_BASE}/rules`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(`Failed to create rule: ${res.statusText}`);
    return res.json();
  },

  async disableRule(ruleId: string) {
    const res = await fetch(`${API_BASE}/rules/${ruleId}/disable`, {
      method: 'POST',
    });
    if (!res.ok) throw new Error(`Failed to disable rule: ${res.statusText}`);
    return res.json();
  },

  async generateCandidate(stagedId: string, patternType: 'exact' | 'prefix' | 'regex' = 'exact') {
    const res = await fetch(`${API_BASE}/rules/candidate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ staged_id: stagedId, pattern_type: patternType }),
    });
    if (!res.ok) throw new Error(`Failed to generate candidate: ${res.statusText}`);
    return res.json();
  },

  async getRuleDrift(ruleId: string): Promise<RuleDrift> {
    const res = await fetch(`${API_BASE}/rules/${ruleId}/drift`);
    if (!res.ok) throw new Error(`Failed to fetch rule drift: ${res.statusText}`);
    return res.json();
  },

  // Projection
  async getBalances(): Promise<BalanceItem[]> {
    const res = await fetch(`${API_BASE}/balances`);
    if (!res.ok) throw new Error(`Failed to fetch balances: ${res.statusText}`);
    return res.json();
  },

  async search(query: string) {
    const res = await fetch(`${API_BASE}/search?q=${encodeURIComponent(query)}`);
    if (!res.ok) throw new Error(`Search failed: ${res.statusText}`);
    return res.json();
  },

  async getFreshness(): Promise<FreshnessStatus> {
    const res = await fetch(`${API_BASE}/projection/freshness`);
    if (!res.ok) throw new Error(`Failed to check freshness: ${res.statusText}`);
    return res.json();
  },

  // Compile
  async compile(dryRun: boolean = false, safeModeToken?: string): Promise<CompileResult> {
    const res = await fetch(`${API_BASE}/compile`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        dry_run: dryRun,
        rebuild_projection: true,
        safe_mode_token: safeModeToken,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Compile request failed: ${res.statusText}`);
    }
    return res.json();
  },

  async simulate(): Promise<CompileResult> {
    const res = await fetch(`${API_BASE}/compile/simulate`, { method: 'POST' });
    if (!res.ok) throw new Error(`Simulation failed: ${res.statusText}`);
    return res.json();
  },

  async getSafeMode(): Promise<SafeModeStatus> {
    const res = await fetch(`${API_BASE}/system/safe-mode`);
    if (!res.ok) throw new Error(`Failed to check safe mode: ${res.statusText}`);
    return res.json();
  },

  async getAudit(): Promise<AuditEvent[]> {
    const res = await fetch(`${API_BASE}/system/audit`);
    if (!res.ok) throw new Error(`Failed to fetch audit: ${res.statusText}`);
    const data = await res.json();
    return data.events || [];
  },

  async getMutations(): Promise<MutationEvent[]> {
    const res = await fetch(`${API_BASE}/system/mutations`);
    if (!res.ok) throw new Error(`Failed to fetch mutations: ${res.statusText}`);
    const data = await res.json();
    return data.mutations || [];
  },
};

