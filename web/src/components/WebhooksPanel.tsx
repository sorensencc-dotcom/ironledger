import React, { useState } from 'react';
import {
  Webhook,
  RefreshCw,
  Plus,
  Send,
  AlertOctagon,
  Clock,
  RotateCcw,
  CheckCircle2,
  ShieldAlert,
} from 'lucide-react';
import type {
  WebhookDelivery,
  WebhookDLQEntry,
  WebhookSubscription,
} from '../types';

interface WebhooksPanelProps {
  subscriptions: WebhookSubscription[];
  deliveries: WebhookDelivery[];
  dlqEntries: WebhookDLQEntry[];
  onCreateSubscription: (targetUrl: string, eventTypes: string[]) => Promise<void>;
  onRedriveDLQ: (dlqEntryId: string) => Promise<void>;
  onRefresh: () => void;
  loading: boolean;
}

export const WebhooksPanel: React.FC<WebhooksPanelProps> = ({
  subscriptions,
  deliveries,
  dlqEntries,
  onCreateSubscription,
  onRedriveDLQ,
  onRefresh,
  loading,
}) => {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [targetUrl, setTargetUrl] = useState('');
  const [selectedEvents, setSelectedEvents] = useState<string[]>([
    'TRANSACTION_STAGED',
    'RULE_MATCHED',
    'COMPILE_COMPLETED',
  ]);
  const [creating, setCreating] = useState(false);
  const [redrivingId, setRedrivingId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!targetUrl.trim()) return;
    setCreating(true);
    setErrorMsg(null);
    try {
      await onCreateSubscription(targetUrl.trim(), selectedEvents);
      setTargetUrl('');
      setIsModalOpen(false);
    } catch (err: any) {
      setErrorMsg(err.message || 'Failed to create webhook subscription');
    } finally {
      setCreating(false);
    }
  };

  const handleRedrive = async (dlqId: string) => {
    setRedrivingId(dlqId);
    try {
      await onRedriveDLQ(dlqId);
    } finally {
      setRedrivingId(null);
    }
  };

  const toggleEventType = (ev: string) => {
    setSelectedEvents((prev) =>
      prev.includes(ev) ? prev.filter((e) => e !== ev) : [...prev, ev]
    );
  };

  return (
    <div className="flex-1 p-6 overflow-y-auto space-y-6 font-mono text-xs">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-800 pb-3">
        <div>
          <h2 className="text-base font-bold text-slate-100 flex items-center gap-2">
            <Webhook className="w-4 h-4 text-indigo-400" />
            Webhook Outbox & Dead-Letter Queue (DLQ) Inspector
          </h2>
          <p className="text-slate-500 text-xs">
            Transactional outbox subscriptions, delivery leases, and dead-letter recovery
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setIsModalOpen(true)}
            className="px-3 py-1 rounded bg-indigo-600 hover:bg-indigo-500 text-white font-sans text-xs flex items-center gap-1.5 transition-colors shadow-sm"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Add Subscription</span>
          </button>
          <button
            onClick={onRefresh}
            disabled={loading}
            className="px-3 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 flex items-center gap-1.5 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* Subscriptions Registry */}
      <div className="space-y-3">
        <h3 className="text-xs font-bold text-slate-300 uppercase tracking-wider flex items-center gap-2">
          <Send className="w-3.5 h-3.5 text-indigo-400" />
          Active Subscriptions ({subscriptions.length})
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {subscriptions.length === 0 ? (
            <div className="p-4 rounded border border-slate-800 bg-slate-900/60 text-slate-500 text-center col-span-2">
              No webhook subscriptions registered yet. Click &quot;Add Subscription&quot; to configure an endpoint.
            </div>
          ) : (
            subscriptions.map((sub) => (
              <div
                key={sub.subscription_id}
                className="p-3.5 rounded bg-slate-800/60 border border-slate-700/60 space-y-2.5"
              >
                <div className="flex items-center justify-between">
                  <span className="font-bold text-slate-200 truncate">{sub.target_url}</span>
                  <span className="px-1.5 py-0.2 rounded bg-emerald-950 text-emerald-400 border border-emerald-800 text-[10px] font-bold">
                    ACTIVE
                  </span>
                </div>
                <div className="text-[10px] text-slate-500 truncate flex items-center gap-1">
                  <span>Secret:</span>
                  <span className="text-indigo-400 font-mono">{sub.secret_fingerprint_hex.slice(0, 16)}...</span>
                </div>
                <div className="flex flex-wrap gap-1 pt-1">
                  {sub.event_types.map((ev) => (
                    <span
                      key={ev}
                      className="px-1.5 py-0.2 rounded bg-slate-900 text-slate-400 border border-slate-700 text-[10px]"
                    >
                      {ev}
                    </span>
                  ))}
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Dead-Letter Queue (DLQ) Inspector */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-bold text-slate-300 uppercase tracking-wider flex items-center gap-2">
            <AlertOctagon className="w-3.5 h-3.5 text-rose-400" />
            Dead-Letter Queue (DLQ) ({dlqEntries.length})
          </h3>
          {dlqEntries.length > 0 && (
            <span className="text-[10px] px-2 py-0.5 rounded bg-rose-950 text-rose-300 border border-rose-800 font-bold animate-pulse">
              ATTENTION REQUIRED
            </span>
          )}
        </div>

        <div className="border border-slate-800 rounded bg-slate-900/60 overflow-hidden">
          <table className="w-full text-left divide-y divide-slate-800/60">
            <thead className="bg-slate-800/40 text-[10px] text-slate-400 uppercase">
              <tr>
                <th className="px-3 py-2">DLQ ID</th>
                <th className="px-3 py-2">Delivery ID</th>
                <th className="px-3 py-2">Attempts</th>
                <th className="px-3 py-2">Failed (UTC)</th>
                <th className="px-3 py-2">Last Error</th>
                <th className="px-3 py-2 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/40 text-[11px]">
              {dlqEntries.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-3 py-4 text-center text-emerald-400">
                    <CheckCircle2 className="w-4 h-4 inline-block mr-1.5" />
                    DLQ is clean. Zero failed deliveries pending review.
                  </td>
                </tr>
              ) : (
                dlqEntries.map((dlq) => {
                  const isRedriving = redrivingId === dlq.dlq_entry_id;
                  return (
                    <tr key={dlq.dlq_entry_id} className="hover:bg-slate-800/30 transition-colors">
                      <td className="px-3 py-2 font-mono text-slate-300">{dlq.dlq_entry_id.slice(0, 10)}</td>
                      <td className="px-3 py-2 font-mono text-indigo-300">{dlq.delivery_id.slice(0, 10)}</td>
                      <td className="px-3 py-2 text-slate-300 font-bold">{dlq.attempt_count}</td>
                      <td className="px-3 py-2 text-slate-500 font-mono text-[10px]">{dlq.failed_at_utc}</td>
                      <td className="px-3 py-2 text-rose-300 truncate max-w-xs" title={dlq.last_error}>
                        {dlq.last_error}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <button
                          onClick={() => handleRedrive(dlq.dlq_entry_id)}
                          disabled={isRedriving}
                          className="px-2.5 py-1 rounded bg-indigo-600 hover:bg-indigo-500 text-white text-[11px] font-sans inline-flex items-center gap-1 shadow-sm transition-colors disabled:opacity-50"
                        >
                          <RotateCcw className={`w-3 h-3 ${isRedriving ? 'animate-spin' : ''}`} />
                          <span>Redrive</span>
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Delivery Queue & Leases Monitor */}
      <div className="space-y-3">
        <h3 className="text-xs font-bold text-slate-300 uppercase tracking-wider flex items-center gap-2">
          <Clock className="w-3.5 h-3.5 text-slate-400" />
          Delivery Queue Status ({deliveries.length})
        </h3>
        <div className="border border-slate-800 rounded bg-slate-900/60 overflow-hidden">
          <table className="w-full text-left divide-y divide-slate-800/60">
            <thead className="bg-slate-800/40 text-[10px] text-slate-400 uppercase">
              <tr>
                <th className="px-3 py-2">Delivery ID</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Retries</th>
                <th className="px-3 py-2">Lease Holder</th>
                <th className="px-3 py-2">Next Retry (UTC)</th>
                <th className="px-3 py-2">Last Code</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/40 text-[11px]">
              {deliveries.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-3 py-4 text-center text-slate-500">
                    No webhook delivery records.
                  </td>
                </tr>
              ) : (
                deliveries.map((del) => (
                  <tr key={del.delivery_id} className="hover:bg-slate-800/30 transition-colors">
                    <td className="px-3 py-2 font-mono text-slate-300">{del.delivery_id.slice(0, 10)}</td>
                    <td className="px-3 py-2">
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                          del.status === 'DELIVERED'
                            ? 'bg-emerald-950 text-emerald-400'
                            : del.status === 'PROCESSING'
                            ? 'bg-indigo-950 text-indigo-400 animate-pulse'
                            : del.status === 'PENDING'
                            ? 'bg-amber-950 text-amber-400'
                            : 'bg-rose-950 text-rose-400'
                        }`}
                      >
                        {del.status}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-slate-300">{del.retry_count}</td>
                    <td className="px-3 py-2 text-slate-400 font-mono text-[10px]">{del.leased_by || 'Unleased'}</td>
                    <td className="px-3 py-2 text-slate-500 font-mono text-[10px]">{del.next_retry_at_utc}</td>
                    <td className="px-3 py-2 text-slate-300 font-mono">{del.last_status_code || '—'}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Creation Modal */}
      {isModalOpen && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4 font-sans">
          <div className="bg-slate-900 border border-slate-700 rounded-lg max-w-md w-full p-5 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="font-bold text-sm text-slate-100 flex items-center gap-2">
                <Webhook className="w-4 h-4 text-indigo-400" />
                Register Webhook Subscription
              </h3>
              <button
                onClick={() => setIsModalOpen(false)}
                className="text-slate-400 hover:text-slate-200 text-xs"
              >
                ✕
              </button>
            </div>

            {errorMsg && (
              <div className="p-2.5 rounded bg-rose-950/80 border border-rose-800 text-rose-300 text-xs flex items-center gap-2">
                <ShieldAlert className="w-4 h-4 shrink-0" />
                <span>{errorMsg}</span>
              </div>
            )}

            <form onSubmit={handleCreate} className="space-y-3 font-mono text-xs">
              <div className="space-y-1">
                <label className="text-slate-300">Target Endpoint URL</label>
                <input
                  type="text"
                  placeholder="https://api.yourdomain.com/webhooks"
                  value={targetUrl}
                  onChange={(e) => setTargetUrl(e.target.value)}
                  className="w-full px-3 py-2 rounded bg-slate-800 border border-slate-700 text-slate-100 text-xs focus:outline-none focus:border-indigo-500"
                  required
                />
                <p className="text-[10px] text-slate-500 font-sans">
                  SSRF Protected: Private and metadata IPs (e.g. 169.254.169.254) are forbidden.
                </p>
              </div>

              <div className="space-y-1.5 pt-1">
                <label className="text-slate-300">Subscribed Event Types</label>
                <div className="space-y-1">
                  {['TRANSACTION_STAGED', 'RULE_MATCHED', 'COMPILE_COMPLETED'].map((ev) => (
                    <label key={ev} className="flex items-center gap-2 cursor-pointer text-slate-300 text-xs">
                      <input
                        type="checkbox"
                        checked={selectedEvents.includes(ev)}
                        onChange={() => toggleEventType(ev)}
                        className="rounded bg-slate-800 border-slate-700 text-indigo-600 focus:ring-0"
                      />
                      <span>{ev}</span>
                    </label>
                  ))}
                </div>
              </div>

              <div className="flex items-center justify-end gap-2 pt-3 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  className="px-3 py-1.5 rounded text-xs text-slate-400 hover:text-slate-200 font-sans"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creating}
                  className="px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-sans flex items-center gap-1.5 transition-colors disabled:opacity-50"
                >
                  {creating ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : null}
                  <span>Save Endpoint</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
