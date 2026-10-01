export interface Posting {
  account: string;
  currency: string;
  minor_units: number;
  scale: number;
  role?: string | null;
}

export interface AttachCandidate {
  staged_id: string;
  payee: string;
  date: string;
  minor_units: number;
  category_account?: string | null;
}

export interface AttachProposal {
  proposal_id: string;
  kind: 'unique' | 'ambiguous' | 'near_miss';
  status: string;
  pdf_description: string;
  date: string;
  currency: string;
  minor_units: number;
  scale: number;
  source_document_id: string;
  source_record_id: string;
  candidates: AttachCandidate[];
  item_type: 'attach';
}


export interface SplitProposalLine {
  line_index: number;
  item_title?: string | null;
  item_description?: string | null;
  quantity?: number | null;
  unit_price_minor?: number | null;
  total_price_minor: number;
  proposed_account?: string | null;
  confidence_score?: number | null;
}

export interface SplitProposal {
  proposal_id: string;
  order_id: string;
  target_type: string;
  target_id: string;
  parent_amount_minor: number;
  match_confidence: number | null;
  status: string;
  created_at_utc: string;
  merchant: string;
  order_date: string;
  total_minor_units: number;
  currency: string;
  lines?: SplitProposalLine[];
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
  category_account?: string | null;
  status: 'pending' | 'categorized' | 'approved' | 'rejected';
  confidence_score: number | null;
  matched_rule_id: string | null;
  notes: string | null;
  external_id?: string | null;
  raw_payload_ref?: string | null;
  provenance?: string | null;
  item_type?: 'staged' | 'attach' | 'split';
  proposal_id?: string;
  split_proposal?: SplitProposal;
  attach_kind?: 'unique' | 'ambiguous' | 'near_miss';
  candidates?: AttachCandidate[];
  pdf_description?: string;
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

export interface TaxonomyCategory { keywords: string[]; account: string; }

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

export interface StagedPortfolioSummary {
  staged_transaction_count: number;
  investment_candidate_count: number;
  candidates: StagedInvestmentCandidate[];
}

export interface StagedInvestmentCandidate {
  date: string;
  payee: string;
  account: string;
  currency: string;
  minor_units: number;
  minor_unit_scale: number;
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
  version?: string;
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

export type TaxTerm = 'ALL' | 'SHORT_TERM' | 'LONG_TERM';

export interface TaxTermSummary {
  realized_gain_minor: number;
  realized_gain_display: string;
  proceeds_minor: number;
  proceeds_display: string;
  cost_basis_minor: number;
  cost_basis_display: string;
}

export interface CapitalGainsSummary {
  ledger_id: string;
  functional_currency: string;
  tax_year: number | null;
  term_filter: TaxTerm;
  total_realized_gain_minor: number;
  total_realized_gain_display: string;
  total_proceeds_minor: number;
  total_proceeds_display: string;
  total_cost_basis_minor: number;
  total_cost_basis_display: string;
  short_term: TaxTermSummary;
  long_term: TaxTermSummary;
  disposal_count: number;
}

export interface OpenTaxLot {
  lot_key: string;
  account: string;
  commodity: string;
  acquisition_date: string;
  remaining_units_minor: number;
  unit_scale: number;
  quantity_display: string;
  functional_currency: string;
  current_basis_minor: number;
  current_basis_display: string;
  market_value_display: string | null;
  unrealized_gain_loss_display: string | null;
}

export interface OpenTaxLots { lots: OpenTaxLot[]; count: number }

export interface UnrealizedPosition {
  commodity: string;
  quantity_display: string;
  functional_currency: string;
  cost_basis_display: string;
  latest_price_display: string;
  market_value_display: string;
  unrealized_gain_minor: number;
  unrealized_gain_display: string;
}

export interface UnrealizedGains {
  ledger_id: string;
  functional_currency: string;
  total_cost_basis_display: string;
  total_market_value_display: string;
  total_unrealized_gain_minor: number;
  total_unrealized_gain_display: string;
  positions: UnrealizedPosition[];
}

export interface DisposalPreviewRequest {
  ledger_id?: string;
  commodity: string;
  quantity: string;
  proceeds_rate: string;
  strategy: 'FIFO' | 'LIFO' | 'HIFO';
  disposal_date?: string;
  account?: string;
}

export interface DisposalPreview {
  simulation_status: 'SUCCESS';
  commodity: string;
  strategy: 'FIFO' | 'LIFO' | 'HIFO';
  disposal_date: string;
  units_disposed_display: string;
  total_proceeds_display: string;
  total_cost_basis_display: string;
  total_realized_gain_minor: number;
  total_realized_gain_display: string;
  short_term_gain_display: string;
  long_term_gain_display: string;
}

export type ComplianceFramework = 'SOC2_TYPE2' | 'ISO27001' | 'SOX' | 'CUSTOM';

export interface ComplianceBundleGenerateRequest {
  ledger_id?: string;
  framework: ComplianceFramework;
  period_start_utc: string;
  period_end_utc: string;
}

export interface ComplianceBundle {
  ledger_id: string;
  bundle_id: string;
  framework: ComplianceFramework;
  period_start_utc: string;
  period_end_utc: string;
  merkle_root_hex: string;
  sealed_archive_sha256: string;
  record_count: number;
  manifest: Record<string, unknown>;
}

export interface ComplianceBundleVerification {
  is_valid: boolean;
  bundle_id: string;
  ledger_id: string;
  framework: ComplianceFramework;
  merkle_root_hex: string;
  sealed_archive_sha256: string;
  record_count: number;
  manifest: Record<string, unknown>;
}

export type AnomalyRuleType = 'DUPLICATE_CHARGE' | 'VELOCITY_SPIKE' | 'RATIONAL_OUTLIER' | 'UNUSUAL_PAYEE';
export type AnomalySeverity = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
export type AnomalyResolution = 'DISMISSED' | 'CONFIRMED_FRAUD' | 'RESOLVED_VALID';

export interface AnomalyFinding {
  flag_id: string;
  ledger_id: string;
  staged_transaction_id: string;
  rule_type: AnomalyRuleType;
  severity: AnomalySeverity;
  score_numerator: number;
  score_denominator: number;
  details: Record<string, unknown>;
  created_at_utc: string;
}

export interface AnomalyScanResult {
  ledger_id: string;
  scanned_count: number;
  findings: AnomalyFinding[];
}

export interface AnomalyFlag {
  flag_id: string;
  staged_transaction_id: string;
  rule_type: AnomalyRuleType;
  severity: AnomalySeverity;
  score_numerator: number;
  score_denominator: number;
  resolution_status: AnomalyResolution | null;
  created_at_utc: string;
}

export interface AnomalyFlagsList {
  ledger_id: string;
  flags: AnomalyFlag[];
  count: number;
}

export interface AnomalyResolveRequest {
  resolution_status: AnomalyResolution;
  actor: string;
  reason?: string;
}
