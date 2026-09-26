import type {
  AuditEvent,
  BalanceItem,
  CompileResult,
  ConnectorCredentialStatus,
  ConnectorProvider,
  ConnectorSyncRun,
  FreshnessStatus,
  HealthStatus,
  MutationEvent,
  Posting,
  RedriveDLQResult,
  Rule,
  RuleDrift,
  SafeModeStatus,
  StagedTransaction,
  SyncPollResult,
  SyncStatus,
  SyncTimelineEvent,
  TriggerSyncResult,
  WebhookDelivery,
  WebhookDLQEntry,
  WebhookSubscription,
  FederationTenant,
  FederationClusterNode,
  FederatedOutboxEvent,
  FailoverStatus,
  KeyRotationResult,
  SankeyFlowRow,
  HoldingRecord,
  StagedPortfolioSummary,
  WatchlistData,
  PriceSyncResult,
  AttachProposal,
  CapitalGainsSummary,
  DisposalPreview,
  DisposalPreviewRequest,
  OpenTaxLots,
  TaxTerm,
  UnrealizedGains,
  ComplianceBundle,
  ComplianceBundleGenerateRequest,
  ComplianceBundleVerification,
  AnomalyRuleType,
  AnomalyFlagsList,
  AnomalyScanResult,
  AnomalyResolveRequest,
} from './types';


const API_BASE = '/api';

let cachedCsrfToken: string | null = null;

const request = (input: RequestInfo | URL, init: RequestInit = {}) =>
  fetch(input, { ...init, signal: init.signal ?? AbortSignal.timeout(15000) });

const getHeaders = (extra: Record<string, string> = {}) => {
  const token = localStorage.getItem('ironledger_op_token') || 'd0-localhost-token';
  const ledgerId = localStorage.getItem('ironledger_active_ledger') || 'default';
  const headers: Record<string, string> = {
    'X-IronLedger-Op-Token': token,
    'X-IronLedger-Ledger-Id': ledgerId,
    ...extra,
  };
  if (cachedCsrfToken) {
    headers['X-CSRF-Token'] = cachedCsrfToken;
  }
  return headers;
};

const generateIdempotencyKey = (prefix: string = 'key') => {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
};

export const api = {
  async getCapitalGainsSummary(params: { tax_year?: string; term?: TaxTerm; account?: string; commodity?: string } = {}): Promise<CapitalGainsSummary> {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => { if (value) query.set(key, value); });
    const res = await fetch(`${API_BASE}/tax/capital-gains-summary?${query}`, { headers: getHeaders() });
    if (!res.ok) throw new Error(`Failed to fetch capital gains: ${res.statusText}`);
    return res.json();
  },

  async getOpenTaxLots(params: { account?: string; commodity?: string } = {}): Promise<OpenTaxLots> {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => { if (value) query.set(key, value); });
    const res = await fetch(`${API_BASE}/tax/open-lots?${query}`, { headers: getHeaders() });
    if (!res.ok) throw new Error(`Failed to fetch open tax lots: ${res.statusText}`);
    return res.json();
  },

  async getUnrealizedGains(commodity?: string): Promise<UnrealizedGains> {
    const query = commodity ? `?commodity=${encodeURIComponent(commodity)}` : '';
    const res = await fetch(`${API_BASE}/tax/unrealized-gains${query}`, { headers: getHeaders() });
    if (!res.ok) throw new Error(`Failed to fetch unrealized gains: ${res.statusText}`);
    return res.json();
  },

  async previewLotDisposal(payload: DisposalPreviewRequest): Promise<DisposalPreview> {
    const res = await fetch(`${API_BASE}/tax/preview-disposal`, {
      method: 'POST', headers: getHeaders({ 'Content-Type': 'application/json' }), body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({}));
      throw new Error(error.detail || `Failed to preview disposal: ${res.statusText}`);
    }
    return res.json();
  },

  // Compliance
  async generateComplianceBundle(payload: ComplianceBundleGenerateRequest): Promise<ComplianceBundle> {
    const res = await fetch(`${API_BASE}/compliance/bundles`, {
      method: 'POST', headers: getHeaders({ 'Content-Type': 'application/json' }), body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({}));
      throw new Error(error.detail || `Failed to generate compliance bundle: ${res.statusText}`);
    }
    return res.json();
  },

  async verifyComplianceBundle(archive: File, expectedMerkleRoot?: string, expectedSha256?: string): Promise<ComplianceBundleVerification> {
    const query = new URLSearchParams();
    if (expectedMerkleRoot) query.set('expected_merkle_root', expectedMerkleRoot);
    if (expectedSha256) query.set('expected_sha256', expectedSha256);
    const form = new FormData();
    form.append('archive', archive);
    const res = await fetch(`${API_BASE}/compliance/bundles/verify?${query}`, {
      method: 'POST', headers: getHeaders(), body: form,
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({}));
      throw new Error(error.detail || `Failed to verify compliance bundle: ${res.statusText}`);
    }
    return res.json();
  },

  // Anomaly
  async getAnomalyFlags(params: { ledgerId?: string; status?: string } = {}): Promise<AnomalyFlagsList> {
    const query = new URLSearchParams();
    if (params.ledgerId) query.set('ledger_id', params.ledgerId);
    if (params.status) query.set('status', params.status);
    const res = await fetch(`${API_BASE}/anomaly/flags?${query}`, { headers: getHeaders() });
    if (!res.ok) throw new Error(`Failed to fetch anomaly flags: ${res.statusText}`);
    return res.json();
  },

  async scanAnomalies(ledgerId: string = 'default', rules?: AnomalyRuleType[]): Promise<AnomalyScanResult> {
    const res = await fetch(`${API_BASE}/anomaly/scan`, {
      method: 'POST', headers: getHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ ledger_id: ledgerId, rules: rules ?? null }),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({}));
      throw new Error(error.detail || `Failed to scan for anomalies: ${res.statusText}`);
    }
    return res.json();
  },

  async resolveAnomalyFlag(flagId: string, payload: AnomalyResolveRequest, ledgerId: string = 'default'): Promise<{ success: boolean; flag_id: string; resolution_status: string }> {
    const res = await fetch(`${API_BASE}/anomaly/flags/${flagId}/resolve?ledger_id=${encodeURIComponent(ledgerId)}`, {
      method: 'POST', headers: getHeaders({ 'Content-Type': 'application/json' }), body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({}));
      throw new Error(error.detail || `Failed to resolve anomaly flag: ${res.statusText}`);
    }
    return res.json();
  },

  // Staging
  async getAttachProposals(): Promise<AttachProposal[]> {
    const res = await fetch(`${API_BASE}/staging/proposals`, { headers: getHeaders() });
    if (!res.ok) throw new Error(`Failed to fetch attach proposals: ${res.statusText}`);
    return res.json();
  },

  async confirmAttach(proposalId: string, chosenStagedId: string) {
    const res = await fetch(`${API_BASE}/staging/proposals/${proposalId}/confirm`, {
      method: 'POST',
      headers: getHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ chosen_staged_id: chosenStagedId }),
    });
    if (!res.ok) throw new Error(`Failed to confirm attach: ${res.statusText}`);
    return res.json();
  },

  async rejectAttach(proposalId: string) {
    const res = await fetch(`${API_BASE}/staging/proposals/${proposalId}/reject`, {
      method: 'POST',
      headers: getHeaders({ 'Content-Type': 'application/json' }),
    });
    if (!res.ok) throw new Error(`Failed to reject attach: ${res.statusText}`);
    return res.json();
  },

  async getStaging(status?: string): Promise<StagedTransaction[]> {
    const url = status ? `${API_BASE}/staging?status=${status}` : `${API_BASE}/staging`;
    const res = await fetch(url, { headers: getHeaders() });
    if (!res.ok) throw new Error(`Failed to fetch staging: ${res.statusText}`);
    return res.json();
  },

  async autoMatch() {
    const res = await fetch(`${API_BASE}/staging/auto-match`, {
      method: 'POST',
      headers: getHeaders(),
    });
    if (!res.ok) throw new Error(`Failed to scan rules: ${res.statusText}`);
    return res.json() as Promise<{ matched: number; candidates: number }>;
  },

  async categorize(stagedId: string, targetAccount: string, notes?: string) {
    const res = await fetch(`${API_BASE}/staging/${stagedId}/categorize`, {
      method: 'POST',
      headers: getHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ target_account: targetAccount, notes }),
    });
    if (!res.ok) throw new Error(`Failed to categorize: ${res.statusText}`);
    return res.json();
  },

  async approve(stagedId: string, targetAccount?: string) {
    const res = await fetch(`${API_BASE}/staging/${stagedId}/approve`, {
      method: 'POST',
      headers: getHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(targetAccount ? { target_account: targetAccount } : {}),
    });
    if (!res.ok) throw new Error(`Failed to approve: ${res.statusText}`);
    return res.json();
  },

  async reject(stagedId: string, reason?: string) {
    const res = await fetch(`${API_BASE}/staging/${stagedId}/reject`, {
      method: 'POST',
      headers: getHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ reason }),
    });
    if (!res.ok) throw new Error(`Failed to reject: ${res.statusText}`);
    return res.json();
  },

  async split(stagedId: string, postings: Posting[]) {
    const res = await fetch(`${API_BASE}/staging/${stagedId}/split`, {
      method: 'POST',
      headers: getHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ postings }),
    });
    if (!res.ok) throw new Error(`Failed to split: ${res.statusText}`);
    return res.json();
  },

  // Rules
  async getRules(): Promise<Rule[]> {
    const res = await fetch(`${API_BASE}/rules`, { headers: getHeaders() });
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
      headers: getHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => null) as { detail?: string } | null;
      throw new Error(body?.detail || `Failed to create rule: ${res.statusText}`);
    }
    return res.json();
  },

  async disableRule(ruleId: string) {
    const res = await fetch(`${API_BASE}/rules/${ruleId}/disable`, {
      method: 'POST',
      headers: getHeaders(),
    });
    if (!res.ok) throw new Error(`Failed to disable rule: ${res.statusText}`);
    return res.json();
  },

  async generateCandidate(stagedId: string, patternType: 'exact' | 'prefix' | 'regex' = 'exact', payee?: string) {
    const res = await fetch(`${API_BASE}/rules/candidate`, {
      method: 'POST',
      headers: getHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ staged_id: stagedId, pattern_type: patternType, ...(payee ? { payee } : {}) }),
    });
    if (!res.ok) throw new Error(`Failed to generate candidate: ${res.statusText}`);
    return res.json();
  },

  async getRuleDrift(ruleId: string): Promise<RuleDrift> {
    const res = await fetch(`${API_BASE}/rules/${ruleId}/drift`, { headers: getHeaders() });
    if (!res.ok) throw new Error(`Failed to fetch rule drift: ${res.statusText}`);
    return res.json();
  },

  // Projection
  async getBalances(): Promise<BalanceItem[]> {
    const res = await fetch(`${API_BASE}/balances`, { headers: getHeaders() });
    if (!res.ok) throw new Error(`Failed to fetch balances: ${res.statusText}`);
    return res.json();
  },

  async search(query: string) {
    const res = await fetch(`${API_BASE}/search?q=${encodeURIComponent(query)}`, { headers: getHeaders() });
    if (!res.ok) throw new Error(`Search failed: ${res.statusText}`);
    return res.json();
  },

  async getFreshness(): Promise<FreshnessStatus> {
    const res = await fetch(`${API_BASE}/projection/freshness`, { headers: getHeaders() });
    if (!res.ok) throw new Error(`Failed to check freshness: ${res.statusText}`);
    return res.json();
  },

  // Compile
  async compile(dryRun: boolean = false, safeModeToken?: string): Promise<CompileResult> {
    const res = await fetch(`${API_BASE}/compile`, {
      method: 'POST',
      headers: getHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        dry_run: dryRun,
        rebuild_projection: true,
        safe_mode_token: safeModeToken,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.message || err.detail || `Compile request failed: ${res.statusText}`);
    }
    return res.json();
  },

  async simulate(): Promise<CompileResult> {
    const res = await fetch(`${API_BASE}/compile/simulate`, {
      method: 'POST',
      headers: getHeaders(),
    });
    if (!res.ok) throw new Error(`Simulation failed: ${res.statusText}`);
    return res.json();
  },

  async getSafeMode(): Promise<SafeModeStatus> {
    const res = await fetch(`${API_BASE}/system/safe-mode`, { headers: getHeaders() });
    if (!res.ok) throw new Error(`Failed to check safe mode: ${res.statusText}`);
    return res.json();
  },

  async getAudit(): Promise<AuditEvent[]> {
    const res = await fetch(`${API_BASE}/system/audit`, { headers: getHeaders() });
    if (!res.ok) throw new Error(`Failed to fetch audit: ${res.statusText}`);
    const data = await res.json();
    return data.events || [];
  },

  async getMutations(): Promise<MutationEvent[]> {
    const res = await fetch(`${API_BASE}/system/mutations`, { headers: getHeaders() });
    if (!res.ok) throw new Error(`Failed to fetch mutations: ${res.statusText}`);
    const data = await res.json();
    return data.mutations || [];
  },

  // Bank Sync (SimpleFIN)
  async getSyncStatus(): Promise<SyncStatus> {
    const res = await fetch(`${API_BASE}/sync/status`, {
      headers: getHeaders(),
    });
    if (!res.ok) throw new Error(`Failed to fetch sync status: ${res.statusText}`);
    const data: SyncStatus = await res.json();
    if (data.csrf_token) {
      cachedCsrfToken = data.csrf_token;
    }
    return data;
  },

  async pollSync(): Promise<SyncPollResult> {
    if (!cachedCsrfToken) {
      await api.getSyncStatus();
    }
    const res = await fetch(`${API_BASE}/sync/poll`, {
      method: 'POST',
      headers: getHeaders({ 'Content-Type': 'application/json' }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.message || err.detail || `Sync poll failed: ${res.statusText}`);
    }
    return res.json();
  },

  // Connector Governance (Phase 9/10 Option B)
  async getConnectors(): Promise<ConnectorProvider[]> {
    const res = await fetch(`${API_BASE}/connectors`, { headers: getHeaders() });
    if (!res.ok) throw new Error(`Failed to fetch connectors: ${res.statusText}`);
    return res.json();
  },

  async getConnectorCredentials(): Promise<ConnectorCredentialStatus[]> {
    const res = await fetch(`${API_BASE}/connectors/credentials`, { headers: getHeaders() });
    if (!res.ok) throw new Error(`Failed to fetch credentials status: ${res.statusText}`);
    return res.json();
  },

  async getConnectorSyncRuns(limit = 50): Promise<ConnectorSyncRun[]> {
    const res = await fetch(`${API_BASE}/connectors/sync-runs?limit=${limit}`, { headers: getHeaders() });
    if (!res.ok) throw new Error(`Failed to fetch sync runs: ${res.statusText}`);
    return res.json();
  },

  async getConnectorTimeline(limit = 30): Promise<SyncTimelineEvent[]> {
    const res = await fetch(`${API_BASE}/connectors/timeline?limit=${limit}`, { headers: getHeaders() });
    if (!res.ok) throw new Error(`Failed to fetch timeline: ${res.statusText}`);
    return res.json();
  },

  async triggerConnectorSync(providerId: string): Promise<TriggerSyncResult> {
    const idempKey = generateIdempotencyKey('sync');
    const res = await fetch(`${API_BASE}/connectors/${providerId}/trigger`, {
      method: 'POST',
      headers: getHeaders({
        'Content-Type': 'application/json',
        'Idempotency-Key': idempKey,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.message || err.detail || `Failed to trigger sync for ${providerId}`);
    }
    return res.json();
  },

  // Webhooks & DLQ
  async getWebhookSubscriptions(): Promise<WebhookSubscription[]> {
    const res = await fetch(`${API_BASE}/webhooks/subscriptions`, { headers: getHeaders() });
    if (!res.ok) throw new Error(`Failed to fetch webhook subscriptions: ${res.statusText}`);
    return res.json();
  },

  async createWebhookSubscription(payload: { target_url: string; event_types?: string[] }): Promise<WebhookSubscription> {
    const res = await fetch(`${API_BASE}/webhooks/subscriptions`, {
      method: 'POST',
      headers: getHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.message || err.detail || `Failed to create webhook subscription: ${res.statusText}`);
    }
    return res.json();
  },

  async getWebhookDeliveries(limit = 50): Promise<WebhookDelivery[]> {
    const res = await fetch(`${API_BASE}/webhooks/deliveries?limit=${limit}`, { headers: getHeaders() });
    if (!res.ok) throw new Error(`Failed to fetch webhook deliveries: ${res.statusText}`);
    return res.json();
  },

  async getWebhookDLQ(limit = 50): Promise<WebhookDLQEntry[]> {
    const res = await fetch(`${API_BASE}/webhooks/dlq?limit=${limit}`, { headers: getHeaders() });
    if (!res.ok) throw new Error(`Failed to fetch webhook DLQ: ${res.statusText}`);
    return res.json();
  },

  async redriveWebhookDLQ(dlqEntryId: string): Promise<RedriveDLQResult> {
    const idempKey = generateIdempotencyKey('dlq');
    const res = await fetch(`${API_BASE}/webhooks/dlq/${dlqEntryId}/redrive`, {
      method: 'POST',
      headers: getHeaders({
        'Content-Type': 'application/json',
        'Idempotency-Key': idempKey,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.message || err.detail || `Failed to redrive DLQ entry: ${res.statusText}`);
    }
    return res.json();
  },

  // Health & Metrics
  async getHealthz(): Promise<HealthStatus> {
    const res = await request('/healthz');
    if (!res.ok) throw new Error('Health check failed');
    return res.json();
  },

  async getReadyz(): Promise<HealthStatus> {
    const res = await request('/readyz');
    if (!res.ok) throw new Error('Readiness probe failed');
    return res.json();
  },

  async getMetricsRaw(): Promise<string> {
    const res = await request('/metrics');
    if (!res.ok) throw new Error('Failed to scrape metrics');
    return res.text();
  },

  // Federation & Event Routing (Phase 11)
  async getFederationTenants(): Promise<FederationTenant[]> {
    const res = await fetch(`${API_BASE}/federation/tenants`, { headers: getHeaders() });
    if (!res.ok) throw new Error(`Failed to fetch federation tenants: ${res.statusText}`);
    return res.json();
  },

  async createFederationTenant(payload: { tenant_id: string; name: string; default_ledger_id?: string }): Promise<any> {
    const res = await fetch(`${API_BASE}/federation/tenants`, {
      method: 'POST',
      headers: getHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.message || err.detail || `Failed to create tenant: ${res.statusText}`);
    }
    return res.json();
  },

  async getFederationNodes(): Promise<FederationClusterNode[]> {
    const res = await fetch(`${API_BASE}/federation/nodes`, { headers: getHeaders() });
    if (!res.ok) throw new Error(`Failed to fetch cluster nodes: ${res.statusText}`);
    return res.json();
  },

  async getFederatedEvents(params?: { tenant_id?: string; source?: string; event_type?: string; limit?: number; offset?: number }): Promise<FederatedOutboxEvent[]> {
    const query = new URLSearchParams();
    if (params?.tenant_id) query.set('tenant_id', params.tenant_id);
    if (params?.source) query.set('source', params.source);
    if (params?.event_type) query.set('event_type', params.event_type);
    if (params?.limit) query.set('limit', String(params.limit));
    if (params?.offset) query.set('offset', String(params.offset));

    const res = await fetch(`${API_BASE}/federation/events?${query.toString()}`, { headers: getHeaders() });
    if (!res.ok) throw new Error(`Failed to fetch federated events: ${res.statusText}`);
    return res.json();
  },

  // Failover & Key Rotation (Phase 12)
  async getFailoverStatus(clusterId: string = 'primary-cluster'): Promise<FailoverStatus> {
    const res = await fetch(`${API_BASE}/failover/status?cluster_id=${encodeURIComponent(clusterId)}`, { headers: getHeaders() });
    if (!res.ok) throw new Error(`Failed to fetch failover status: ${res.statusText}`);
    return res.json();
  },

  async recordFailoverHeartbeat(payload: {
    cluster_id: string;
    node_id: string;
    role?: string;
    wal_offset_bytes?: number;
    salt1?: number;
    salt2?: number;
  }): Promise<any> {
    const res = await fetch(`${API_BASE}/failover/heartbeat`, {
      method: 'POST',
      headers: getHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.message || err.detail || `Failed to record heartbeat: ${res.statusText}`);
    }
    return res.json();
  },

  async promoteFailoverLeader(payload: {
    cluster_id: string;
    candidate_node_id: string;
    expected_term: number;
    lease_ttl_seconds?: number;
  }): Promise<any> {
    const res = await fetch(`${API_BASE}/failover/promote`, {
      method: 'POST',
      headers: getHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.message || err.detail || `Failed to promote leader: ${res.statusText}`);
    }
    return res.json();
  },

  async rotateTenantKey(payload: {
    tenant_id: string;
    new_kek_key_id: string;
  }): Promise<KeyRotationResult> {
    const res = await fetch(`${API_BASE}/security/rotate-key`, {
      method: 'POST',
      headers: getHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.message || err.detail || `Failed to rotate tenant key: ${res.statusText}`);
    }
    return res.json();
  },

  // Analytics & Visualizations
  async getSankeyData(period: string): Promise<SankeyFlowRow[]> {
    const res = await fetch(`${API_BASE}/analytics/sankey?period=${encodeURIComponent(period)}`, {
      headers: getHeaders(),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.message || err.detail || `Failed to fetch sankey data: ${res.statusText}`);
    }
    return res.json();
  },

  async getPortfolioData(): Promise<HoldingRecord[]> {
    const res = await fetch(`${API_BASE}/analytics/portfolio`, {
      headers: getHeaders(),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.message || err.detail || `Failed to fetch portfolio data: ${res.statusText}`);
    }
    return res.json();
  },

  async getStagedPortfolioSummary(): Promise<StagedPortfolioSummary> {
    const res = await fetch(`${API_BASE}/analytics/portfolio/staged-summary`, {
      headers: getHeaders(),
    });
    if (!res.ok) throw new Error(`Failed to fetch staged portfolio summary: ${res.statusText}`);
    return res.json();
  },

  async getWatchlistData(): Promise<WatchlistData> {
    const res = await fetch(`${API_BASE}/analytics/watchlist`, {
      headers: getHeaders(),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.message || err.detail || `Failed to fetch watchlist: ${res.statusText}`);
    }
    return res.json();
  },

  async triggerPriceSync(symbols?: string[], quoteCurrency?: string): Promise<PriceSyncResult> {
    const res = await fetch(`${API_BASE}/analytics/prices/sync`, {
      method: 'POST',
      headers: getHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(symbols ? { symbols, quote_currency: quoteCurrency || 'USD' } : {}),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.message || err.detail || `Failed to sync prices: ${res.statusText}`);
    }
    return res.json();
  },

  async addWatchlistSymbol(symbol: string, quoteCurrency: string = 'USD', manualQuote?: string): Promise<{ status: string; symbol: string; quote_currency: string }> {
    const res = await fetch(`${API_BASE}/analytics/watchlist/add`, {
      method: 'POST',
      headers: getHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ symbol, quote_currency: quoteCurrency, manual_quote: manualQuote }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.message || err.detail || `Failed to add symbol: ${res.statusText}`);
    }
    return res.json();
  },

  async removeWatchlistSymbol(symbol: string, quoteCurrency: string = 'USD'): Promise<{ status: string; removed_symbol: string; quote_currency: string }> {
    const res = await fetch(`${API_BASE}/analytics/watchlist/${encodeURIComponent(symbol)}?quote_currency=${encodeURIComponent(quoteCurrency)}`, {
      method: 'DELETE',
      headers: getHeaders(),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.message || err.detail || `Failed to remove symbol: ${res.statusText}`);
    }
    return res.json();
  },
};
