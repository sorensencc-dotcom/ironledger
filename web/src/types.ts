export interface Posting {
  account: string;
  currency: string;
  minor_units: number;
  scale: number;
}

export interface StagedTransaction {
  staged_id: string;
  source_document_id: string;
  source_record_id: string;
  date: string;
  payee: string;
  narration: string;
  currency: string;
  minor_units: number;
  scale: number;
  postings: Posting[];
  status: 'pending' | 'categorized' | 'approved' | 'rejected';
  confidence_score: number | null;
  matched_rule_id: string | null;
  notes: string | null;
  external_id?: string | null;
  raw_payload_ref?: string | null;
  provenance?: string | null;
}

export interface SyncStatus {
  state: 'HEALTHY' | 'UNCONFIGURED' | 'DEGRADED';
  pending_count: number;
  last_error_code?: string | null;
  csrf_token?: string | null;
  last_poll_timestamp?: string | null;
}

export interface SyncPollResult {
  inserted: number;
  skipped: number;
}

export interface Rule {
  rule_id: string;
  match_type: 'exact' | 'prefix' | 'regex';
  pattern: string;
  importing_account: string | null;
  target_account: string;
  priority: number;
  active: boolean | number;
  created_at_utc: string;
  disabled_at_utc: string | null;
}

export interface RuleDrift {
  rule_id: string;
  rule_name: string;
  total_hits: number;
  recent_hits: number;
  override_count: number;
  override_rate: number;
  confidence_trend: number;
  drift_status: 'healthy' | 'warning' | 'stale';
}

export interface BalanceItem {
  account: string;
  currency: string;
  minor_units: number;
  scale: number;
  formatted_amount: string;
}

export interface FreshnessStatus {
  is_fresh: boolean;
  latency_seconds: number;
  last_compile_timestamp: string | null;
  last_projection_timestamp: string | null;
  status: 'fresh' | 'stale' | 'critical';
}

export interface SafeModeStatus {
  enabled: boolean;
  token_required: boolean;
  token_active: boolean;
  token_expires_at: string | null;
}

export interface CompileResult {
  success: boolean;
  message: string;
  run_id: string | null;
  dry_run: boolean;
  entries_compiled: number;
  postings_compiled: number;
  diff_preview: string | null;
}

export interface AuditEvent {
  sequence_number: number;
  timestamp_utc: string;
  actor: string;
  action: string;
  target: string;
  result: string;
  event_hash: string;
}

export interface MutationEvent {
  seq: number;
  mutation_id: string;
  ts_utc: string;
  operator_session: string;
  action: string;
  staged_count: number;
  rules_applied: number;
  rules_created: number;
  sha256_before: string;
  sha256_after: string;
  prev_mutation_hash: string;
  mutation_hash: string;
}

// Option B: Governance, Connectors, Webhooks, Metrics Models
export interface ConnectorProvider {
  provider_id: string;
  name: string;
  protocol_type: 'PLAID' | 'SIMPLEFIN' | 'OFX' | 'REST_JSON';
  base_url: string;
  is_active: boolean;
  rate_limit_rpm: number;
  burst_capacity: number;
  circuit_breaker_state: 'CLOSED' | 'OPEN' | 'HALF_OPEN';
  failure_count: number;
  created_at_utc: string;
}

export interface ConnectorCredentialStatus {
  provider_id: string;
  has_credentials: boolean;
  kek_key_id: string | null;
  dek_rotation_age_days: number;
  iv_freshness_status: 'FRESH' | 'STALE' | 'EXPIRED' | 'UNCONFIGURED';
  created_at_utc: string | null;
  updated_at_utc: string | null;
}

export interface ConnectorSyncRun {
  ledger_id: string;
  run_id: string;
  provider_id: string;
  status: 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILED' | 'CIRCUIT_BROKEN';
  records_fetched: number;
  records_staged: number;
  error_code: string | null;
  error_details: string | null;
  started_at_utc: string;
  completed_at_utc: string | null;
}

export interface SyncTimelineEvent {
  event_id: string;
  timestamp_utc: string;
  event_type: string;
  provider_id: string;
  summary: string;
  details: Record<string, any>;
}

export interface TriggerSyncResult {
  run_id: string;
  provider_id: string;
  status: string;
  records_fetched: number;
  records_staged: number;
  message: string;
}

export interface KeyRotationResult {
  tenant_id: string;
  previous_key_version: number;
  new_key_version: number;
  rotated_at_utc: string;
  rewrapped_secrets_count: number;
  vault_digest: string;
}

export interface SankeyFlowRow {
  source_node: string;
  target_node: string;
  amount_minor_units: number;
}

export interface HoldingRecord {
  commodity: string;
  total_units: number;
  total_cost_basis_minor_units: number;
  market_value_minor_units: number;
  unrealized_gain_minor_units: number;
  base_currency: string;
}

export interface WebhookSubscription {
  ledger_id: string;
  subscription_id: string;
  target_url: string;
  secret_fingerprint_hex: string;
  event_types: string[];
  is_active: boolean;
  created_at_utc: string;
}

export interface WebhookDelivery {
  ledger_id: string;
  delivery_id: string;
  event_id: string;
  subscription_id: string;
  status: 'PENDING' | 'PROCESSING' | 'DELIVERED' | 'FAILED' | 'DEAD_LETTERED';
  retry_count: number;
  next_retry_at_utc: string;
  leased_by: string | null;
  leased_until_utc: string | null;
  last_status_code: number | null;
  last_error: string | null;
  created_at_utc: string;
  completed_at_utc: string | null;
}

export interface WebhookDLQEntry {
  ledger_id: string;
  dlq_entry_id: string;
  delivery_id: string;
  event_id: string;
  subscription_id: string;
  status_code: number | null;
  last_error: string;
  attempt_count: number;
  failed_at_utc: string;
}

export interface RedriveDLQResult {
  dlq_entry_id: string;
  delivery_id: string;
  status: string;
  message: string;
}

export interface HealthStatus {
  status: string;
  service: string;
  database?: string;
}

export interface FederationTenant {
  tenant_id: string;
  name: string;
  default_ledger_id: string;
  is_active: boolean;
  created_at_utc: string;
}

export interface FederationClusterNode {
  node_id: string;
  cluster_id: string;
  endpoint_url: string;
  role: 'PRIMARY' | 'REPLICA' | 'WITNESS';
  last_heartbeat_utc: string | null;
  is_active: boolean;
  created_at_utc: string;
}

export interface FederatedOutboxEvent {
  seq: number;
  event_id: string;
  tenant_id: string;
  ledger_id: string;
  event_type: string;
  source: string;
  severity: 'INFO' | 'WARN' | 'ERROR' | 'CRITICAL';
  payload: Record<string, any>;
  metadata: Record<string, any>;
  published_to_peers: boolean;
  created_at_utc: string;
}

export type GovernanceToastCategory =
  | 'SUCCESS_GOVERNANCE_ACTION'
  | 'ERROR_GOVERNANCE_ACTION'
  | 'CIRCUIT_BREAKER_OPEN'
  | 'DLQ_REDRIVE_COMPLETE'
  | 'FAILOVER_LEADER_PROMOTED'
  | 'TENANT_KEY_ROTATED';

export interface LeaderLeaseInfo {
  cluster_id: string;
  leader_node_id: string;
  term: number;
  lease_fence_token: string;
  acquired_at_utc: string;
  lease_expires_at_utc: string;
  is_active: boolean;
}

export interface ClusterNodeStatus {
  node_id: string;
  cluster_id: string;
  endpoint_url: string;
  role: 'PRIMARY' | 'REPLICA' | 'WITNESS';
  is_primary: boolean;
  last_heartbeat_utc: string | null;
  is_alive: boolean;
  lag_bytes?: number;
  salt1?: number;
  salt2?: number;
}

export interface FailoverStatus {
  cluster_id: string;
  primary_node_id: string | null;
  term: number;
  lease_fence_token: string | null;
  is_healthy: boolean;
  nodes: ClusterNodeStatus[];
}

export interface KeyRotationResult {
  success: boolean;
  tenant_id: string;
  new_kek_key_id: string;
  webhooks_reencrypted: number;
  credentials_reencrypted: number;
  audit_event_id: string;
}

export interface WatchlistItem {
  symbol: string;
  quote_currency: string;
  rate_numerator: number | null;
  rate_denominator: number | null;
  price_display: string | null;
  directive_date: string | null;
  last_provider: string;
  last_status: string;
  last_latency_ms: number;
  updated_at: string | null;
  trend?: 'UP' | 'DOWN' | 'FLAT' | null;
  change_percent?: string | null;
  previous_price_display?: string | null;
}


export interface PriceAuditRecord {
  symbol: string;
  quote_currency: string;
  provider_id: string;
  status: string;
  rate_numerator: number | null;
  rate_denominator: number | null;
  latency_ms: number;
  error_message?: string | null;
  created_at: string;
}

export interface WatchlistData {
  quote_currency: string;
  items: WatchlistItem[];
  recent_audit: PriceAuditRecord[];
}

export interface PriceSyncResult {
  status: 'success' | 'partial_failure' | 'failed';
  synced_count: number;
  failed_count: number;
  failed_symbols: string[];
}


