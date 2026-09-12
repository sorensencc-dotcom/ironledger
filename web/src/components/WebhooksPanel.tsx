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
    <div className="flex-1 p-6 overflow-y-auto space-y-6 font-mono text-xs bg-[#0d0a08] relative">
      <div className="ghost-watermark text-[6rem] -top-8 -right-4 select-none pointer-events-none">
        OUTBOX
      </div>

      {/* Header */}
      <div className="flex items-center justify-between border-b border-[#2c2420] pb-3 relative z-10">
        <div>
          <h2 className="text-base font-serif font-bold text-[#f2ece2] flex items-center gap-2">
            <Webhook className="w-4 h-4 text-[#b8922a]" />
            Webhook Outbox & Dead-Letter Queue (DLQ) Inspector
          </h2>
          <p className="text-[#7a6e65] text-xs">
            Transactional outbox subscriptions, delivery leases, and dead-letter recovery
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setIsModalOpen(true)}
            className="px-3 py-1 rounded-none bg-[#c4501a] hover:bg-[#d4622b] text-[#f2ece2] font-mono text-xs uppercase font-bold flex items-center gap-1.5 transition-colors shadow-sm"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Add Subscription</span>
          </button>
          <button
            onClick={onRefresh}
            disabled={loading}
            className="px-3 py-1 rounded-none bg-[#1a1410] hover:bg-[#241c16] text-[#e8dfd1] border border-[#3a2e26] flex items-center gap-1.5 transition-colors text-xs font-mono uppercase tracking-wider disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-[#c4501a]' : 'text-[#b8922a]'}`} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* Subscriptions Registry */}
      <div className="space-y-3 relative z-10">
        <h3 className="text-xs font-bold text-[#b8922a] font-sans uppercase tracking-wider flex items-center gap-2">
          <Send className="w-3.5 h-3.5 text-[#b8922a]" />
          Active Subscriptions ({subscriptions.length})
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {subscriptions.length === 0 ? (
            <div className="p-4 rounded-none border border-[#2c2420] bg-[#1a1410] text-[#7a6e65] text-center col-span-2">
              No webhook subscriptions registered yet. Click &quot;Add Subscription&quot; to configure an endpoint.
            </div>
          ) : (
            subscriptions.map((sub) => (
              <div
                key={sub.subscription_id}
                className="p-3.5 rounded-none bg-[#1a1410] border border-[#2c2420] space-y-2.5"
              >
                <div className="flex items-center justify-between">
                  <span className="font-bold text-[#f2ece2] truncate font-mono">{sub.target_url}</span>
                  <span className="px-1.5 py-0.2 rounded-none bg-[#132a1c] text-[#8fc79e] border border-[#1d442b] text-[10px] font-bold font-mono">
                    ACTIVE
                  </span>
                </div>
                <div className="text-[10px] text-[#7a6e65] truncate flex items-center gap-1 font-mono">
                  <span>Secret:</span>
                  <span className="text-[#b8922a]">{sub.secret_fingerprint_hex.slice(0, 16)}...</span>
                </div>
                <div className="flex flex-wrap gap-1 pt-1">
                  {sub.event_types.map((ev) => (
                    <span
                      key={ev}
                      className="px-1.5 py-0.2 rounded-none bg-[#241c16] text-[#b8922a] border border-[#3a2e26] text-[10px] font-mono"
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
      <div className="space-y-3 relative z-10">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-bold text-[#b8922a] font-sans uppercase tracking-wider flex items-center gap-2">
            <AlertOctagon className="w-3.5 h-3.5 text-[#e2765f]" />
            Dead-Letter Queue (DLQ) ({dlqEntries.length})
          </h3>
          {dlqEntries.length > 0 && (
            <span className="text-[10px] px-2 py-0.5 rounded-none bg-[#2c120e] text-[#e2765f] border border-[#4a1c14] font-bold font-mono animate-pulse">
              ATTENTION REQUIRED
            </span>
          )}
        </div>

        <div className="border border-[#2c2420] rounded-none bg-[#1a1410] overflow-hidden">
          <table className="w-full text-left divide-y divide-[#2c2420]/60">
            <thead className="bg-[#241c16] text-[10px] text-[#7a6e65] font-sans font-bold uppercase tracking-wider">
              <tr>
                <th className="px-3 py-2">DLQ ID</th>
                <th className="px-3 py-2">Delivery ID</th>
                <th className="px-3 py-2">Attempts</th>
                <th className="px-3 py-2">Failed (UTC)</th>
                <th className="px-3 py-2">Last Error</th>
                <th className="px-3 py-2 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#2c2420]/40 text-[11px]">
              {dlqEntries.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-3 py-4 text-center text-[#8fc79e]">
                    <CheckCircle2 className="w-4 h-4 inline-block mr-1.5" />
                    DLQ is clean. Zero failed deliveries pending review.
                  </td>
                </tr>
              ) : (
                dlqEntries.map((dlq) => {
                  const isRedriving = redrivingId === dlq.dlq_entry_id;
                  return (
                    <tr key={dlq.dlq_entry_id} className="hover:bg-[#241c16]/50 transition-colors">
                      <td className="px-3 py-2 font-mono text-[#a89e94]">{dlq.dlq_entry_id.slice(0, 10)}</td>
                      <td className="px-3 py-2 font-mono text-[#b8922a]">{dlq.delivery_id.slice(0, 10)}</td>
                      <td className="px-3 py-2 text-[#f2ece2] font-bold">{dlq.attempt_count}</td>
                      <td className="px-3 py-2 text-[#7a6e65] font-mono text-[10px]">{dlq.failed_at_utc}</td>
                      <td className="px-3 py-2 text-[#e2765f] truncate max-w-xs" title={dlq.last_error}>
                        {dlq.last_error}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <button
                          onClick={() => handleRedrive(dlq.dlq_entry_id)}
                          disabled={isRedriving}
                          className="px-2.5 py-1 rounded-none bg-[#c4501a] hover:bg-[#d4622b] text-[#f2ece2] text-[11px] font-mono uppercase font-bold inline-flex items-center gap-1 shadow-sm transition-colors disabled:opacity-50"
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
      <div className="space-y-3 relative z-10">
        <h3 className="text-xs font-bold text-[#b8922a] font-sans uppercase tracking-wider flex items-center gap-2">
          <Clock className="w-3.5 h-3.5 text-[#7a6e65]" />
          Delivery Queue Status ({deliveries.length})
        </h3>
        <div className="border border-[#2c2420] rounded-none bg-[#1a1410] overflow-hidden">
          <table className="w-full text-left divide-y divide-[#2c2420]/60">
            <thead className="bg-[#241c16] text-[10px] text-[#7a6e65] font-sans font-bold uppercase tracking-wider">
              <tr>
                <th className="px-3 py-2">Delivery ID</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Retries</th>
                <th className="px-3 py-2">Lease Holder</th>
                <th className="px-3 py-2">Next Retry (UTC)</th>
                <th className="px-3 py-2">Last Code</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#2c2420]/40 text-[11px]">
              {deliveries.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-3 py-4 text-center text-[#7a6e65]">
                    No webhook delivery records.
                  </td>
                </tr>
              ) : (
                deliveries.map((del) => (
                  <tr key={del.delivery_id} className="hover:bg-[#241c16]/50 transition-colors">
                    <td className="px-3 py-2 font-mono text-[#a89e94]">{del.delivery_id.slice(0, 10)}</td>
                    <td className="px-3 py-2">
                      <span
                        className={`px-1.5 py-0.5 rounded-none text-[10px] font-bold font-mono ${
                          del.status === 'DELIVERED'
                            ? 'bg-[#132a1c] text-[#8fc79e] border border-[#1d442b]'
                            : del.status === 'PROCESSING'
                            ? 'bg-[#2c1a14] text-[#c4501a] border border-[#c4501a] animate-pulse'
                            : del.status === 'PENDING'
                            ? 'bg-[#2a1d0d] text-[#e0a84c] border border-[#4a3518]'
                            : 'bg-[#2c120e] text-[#e2765f] border border-[#4a1c14]'
                        }`}
                      >
                        {del.status}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-[#a89e94]">{del.retry_count}</td>
                    <td className="px-3 py-2 text-[#7a6e65] font-mono text-[10px]">{del.leased_by || 'Unleased'}</td>
                    <td className="px-3 py-2 text-[#7a6e65] font-mono text-[10px]">{del.next_retry_at_utc}</td>
                    <td className="px-3 py-2 text-[#f2ece2] font-mono">{del.last_status_code || '—'}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Creation Modal */}
      {isModalOpen && (
        <div className="fixed inset-0 bg-black/75 backdrop-blur-md flex items-center justify-center z-50 p-4 font-sans select-none">
          <div className="bg-[#1a1410] border border-[#3a2e26] rounded-none max-w-md w-full p-5 space-y-4 shadow-2xl relative overflow-hidden">
            <div className="ghost-watermark text-[5rem] -top-6 -right-4 select-none pointer-events-none">
              WEBHOOK
            </div>

            <div className="flex items-center justify-between border-b border-[#2c2420] pb-3 relative z-10">
              <h3 className="font-serif font-bold text-sm text-[#f2ece2] flex items-center gap-2">
                <Webhook className="w-4 h-4 text-[#b8922a]" />
                Register Webhook Subscription
              </h3>
              <button
                onClick={() => setIsModalOpen(false)}
                className="text-[#7a6e65] hover:text-[#f2ece2] text-xs transition-colors"
              >
                ✕
              </button>
            </div>

            {errorMsg && (
              <div className="p-2.5 rounded-none bg-[#2c120e] border border-[#4a1c14] text-[#e2765f] text-xs flex items-center gap-2 relative z-10 font-mono">
                <ShieldAlert className="w-4 h-4 shrink-0" />
                <span>{errorMsg}</span>
              </div>
            )}

            <form onSubmit={handleCreate} className="space-y-3 font-mono text-xs relative z-10">
              <div className="space-y-1">
                <label className="text-[#a89e94] uppercase font-sans font-bold text-[10px]">Target Endpoint URL</label>
                <input
                  type="text"
                  placeholder="https://api.yourdomain.com/webhooks"
                  value={targetUrl}
                  onChange={(e) => setTargetUrl(e.target.value)}
                  className="w-full px-3 py-2 rounded-none bg-[#0d0a08] border border-[#3a2e26] text-[#f2ece2] text-xs font-mono focus:outline-none focus:border-[#c4501a]"
                  required
                />
                <p className="text-[10px] text-[#7a6e65] font-sans">
                  SSRF Protected: Private and metadata IPs (e.g. 169.254.169.254) are forbidden.
                </p>
              </div>

              <div className="space-y-1.5 pt-1">
                <label className="text-[#a89e94] uppercase font-sans font-bold text-[10px]">Subscribed Event Types</label>
                <div className="space-y-1">
                  {['TRANSACTION_STAGED', 'RULE_MATCHED', 'COMPILE_COMPLETED'].map((ev) => (
                    <label key={ev} className="flex items-center gap-2 cursor-pointer text-[#e8dfd1] text-xs">
                      <input
                        type="checkbox"
                        checked={selectedEvents.includes(ev)}
                        onChange={() => toggleEventType(ev)}
                        className="rounded-none bg-[#0d0a08] border-[#3a2e26] text-[#c4501a] focus:ring-0"
                      />
                      <span>{ev}</span>
                    </label>
                  ))}
                </div>
              </div>

              <div className="flex items-center justify-end gap-2 pt-3 border-t border-[#2c2420]">
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  className="px-3.5 py-1.5 rounded-none text-xs text-[#7a6e65] hover:text-[#f2ece2] bg-[#1a1410] border border-[#3a2e26] font-mono uppercase"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creating}
                  className="px-3.5 py-1.5 rounded-none bg-[#c4501a] hover:bg-[#d4622b] text-[#f2ece2] text-xs font-mono uppercase font-bold flex items-center gap-1.5 transition-colors disabled:opacity-50"
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
