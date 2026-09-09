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
  event_id: string;
  sequence_number: number;
  timestamp_utc: string;
  actor: string;
  action: string;
  target: string;
  result: string;
  event_hash: string;
}

