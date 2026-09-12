import React, { useState, useEffect } from 'react';
import {
  Network,
  Server,
  Layers,
  CheckCircle2,
  RefreshCw,
  Radio,
  PlusCircle,
  Eye,
  X,
} from 'lucide-react';
import { api } from '../api';

import {
  FederationTenant,
  FederationClusterNode,
  FederatedOutboxEvent,
} from '../types';

interface FederationViewProps {
  onNotify?: (message: string, type?: 'success' | 'error' | 'info') => void;
}

export const FederationView: React.FC<FederationViewProps> = ({ onNotify }) => {
  const [tenants, setTenants] = useState<FederationTenant[]>([]);
  const [nodes, setNodes] = useState<FederationClusterNode[]>([]);
  const [events, setEvents] = useState<FederatedOutboxEvent[]>([]);
  const [selectedTenant, setSelectedTenant] = useState<string>('all');
  const [selectedSource, setSelectedSource] = useState<string>('all');
  const [loading, setLoading] = useState(true);
  const [inspectingEvent, setInspectingEvent] = useState<FederatedOutboxEvent | null>(null);

  // New tenant modal
  const [showTenantModal, setShowTenantModal] = useState(false);
  const [newTenantId, setNewTenantId] = useState('');
  const [newTenantName, setNewTenantName] = useState('');
  const [submittingTenant, setSubmittingTenant] = useState(false);

  const loadData = async () => {
    try {
      setLoading(true);
      const [tenantsData, nodesData, eventsData] = await Promise.all([
        api.getFederationTenants().catch(() => []),
        api.getFederationNodes().catch(() => []),
        api.getFederatedEvents({
          tenant_id: selectedTenant === 'all' ? undefined : selectedTenant,
          source: selectedSource === 'all' ? undefined : selectedSource,
          limit: 50,
        }).catch(() => []),
      ]);
      setTenants(tenantsData);
      setNodes(nodesData);
      setEvents(eventsData);
    } catch (err: any) {
      onNotify?.(err.message || 'Failed to load federation data', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [selectedTenant, selectedSource]);

  const handleCreateTenant = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTenantId || !newTenantName) return;
    try {
      setSubmittingTenant(true);
      await api.createFederationTenant({
        tenant_id: newTenantId,
        name: newTenantName,
        default_ledger_id: 'default',
      });
      onNotify?.(`Tenant ${newTenantId} created`, 'success');
      setShowTenantModal(false);
      setNewTenantId('');
      setNewTenantName('');
      loadData();
    } catch (err: any) {
      onNotify?.(err.message || 'Failed to create tenant', 'error');
    } finally {
      setSubmittingTenant(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Top Header & Actions */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 bg-slate-900 border border-slate-800 p-6 rounded-xl shadow-lg">
        <div>
          <div className="flex items-center gap-3">
            <Network className="w-7 h-7 text-indigo-400" />
            <h1 className="text-2xl font-bold text-white tracking-tight">
              Multi-Tenant Federation & Event Routing
            </h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
              gov.event.v1
            </span>
          </div>
          <p className="text-sm text-slate-400 mt-1">
            Cross-cluster audit propagation, tenant domain isolation, and outbox event streaming.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => setShowTenantModal(true)}
            className="flex items-center gap-2 px-3.5 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm font-medium transition shadow-md"
          >
            <PlusCircle className="w-4 h-4" />
            Add Tenant
          </button>
          <button
            onClick={loadData}
            disabled={loading}
            className="p-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-sm font-medium transition border border-slate-700"
            title="Refresh"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Cluster Nodes & Tenant Domains Top Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Tenant Registry Cards */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Layers className="w-5 h-5 text-indigo-400" />
              <h2 className="text-sm font-semibold text-white uppercase tracking-wider">
                Tenant Domains ({tenants.length})
              </h2>
            </div>
            <select
              value={selectedTenant}
              onChange={(e) => setSelectedTenant(e.target.value)}
              className="bg-slate-800 text-slate-200 text-xs rounded px-2 py-1 border border-slate-700 focus:outline-none focus:border-indigo-500"
            >
              <option value="all">All Tenants</option>
              {tenants.map((t) => (
                <option key={t.tenant_id} value={t.tenant_id}>
                  {t.name} ({t.tenant_id})
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-2.5 max-h-56 overflow-y-auto pr-1">
            {tenants.map((t) => (
              <div
                key={t.tenant_id}
                className="flex items-center justify-between p-3 rounded-lg bg-slate-800/60 border border-slate-800"
              >
                <div>
                  <div className="text-sm font-medium text-slate-200">{t.name}</div>
                  <div className="text-xs text-slate-400 font-mono">id: {t.tenant_id} • ledger: {t.default_ledger_id}</div>
                </div>
                <span className="flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                  <CheckCircle2 className="w-3 h-3" />
                  Active
                </span>
              </div>
            ))}
            {tenants.length === 0 && (
              <div className="text-center py-6 text-sm text-slate-500">No tenants registered</div>
            )}
          </div>
        </div>

        {/* Peer Cluster Topologies */}
        <div className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Server className="w-5 h-5 text-indigo-400" />
              <h2 className="text-sm font-semibold text-white uppercase tracking-wider">
                Cluster Node Topology ({nodes.length})
              </h2>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-slate-400 border-b border-slate-800">
                <tr>
                  <th className="pb-2 font-medium">Node ID</th>
                  <th className="pb-2 font-medium">Cluster</th>
                  <th className="pb-2 font-medium">Role</th>
                  <th className="pb-2 font-medium">Endpoint URL</th>
                  <th className="pb-2 font-medium">Heartbeat</th>
                  <th className="pb-2 font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 text-slate-300">
                {nodes.map((node) => (
                  <tr key={node.node_id} className="hover:bg-slate-800/30">
                    <td className="py-2.5 font-mono font-medium text-indigo-300">{node.node_id}</td>
                    <td className="py-2.5">{node.cluster_id}</td>
                    <td className="py-2.5">
                      <span className={`px-2 py-0.5 rounded font-mono text-[10px] ${
                        node.role === 'PRIMARY' ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20' :
                        node.role === 'REPLICA' ? 'bg-blue-500/10 text-blue-400 border border-blue-500/20' :
                        'bg-purple-500/10 text-purple-400 border border-purple-500/20'
                      }`}>
                        {node.role}
                      </span>
                    </td>
                    <td className="py-2.5 font-mono text-slate-400 truncate max-w-[180px]">{node.endpoint_url}</td>
                    <td className="py-2.5 text-slate-400">{node.last_heartbeat_utc ? new Date(node.last_heartbeat_utc).toLocaleTimeString() : 'N/A'}</td>
                    <td className="py-2.5">
                      <span className="flex items-center gap-1 text-emerald-400">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
                        ONLINE
                      </span>
                    </td>
                  </tr>
                ))}
                {nodes.length === 0 && (
                  <tr>
                    <td colSpan={6} className="text-center py-6 text-slate-500">
                      Primary standalone node active. Peer cluster sync ready.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Federated Event Outbox Stream */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-sm">
        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-5">
          <div className="flex items-center gap-2">
            <Radio className="w-5 h-5 text-indigo-400" />
            <h2 className="text-base font-semibold text-white">
              Federated Governance Event Stream (gov.event.v1)
            </h2>
          </div>

          <div className="flex items-center gap-3">
            <label className="text-xs text-slate-400">Source:</label>
            <select
              value={selectedSource}
              onChange={(e) => setSelectedSource(e.target.value)}
              className="bg-slate-800 text-slate-200 text-xs rounded px-2 py-1 border border-slate-700 focus:outline-none focus:border-indigo-500"
            >
              <option value="all">All Sources</option>
              <option value="compliance">Compliance</option>
              <option value="anomaly">Anomaly</option>
              <option value="replication">Replication</option>
              <option value="connector">Connector</option>
              <option value="webhook">Webhook</option>
            </select>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-slate-400 border-b border-slate-800 uppercase tracking-wider text-[10px]">
              <tr>
                <th className="pb-3 font-semibold">Seq</th>
                <th className="pb-3 font-semibold">Event Type</th>
                <th className="pb-3 font-semibold">Source</th>
                <th className="pb-3 font-semibold">Tenant / Ledger</th>
                <th className="pb-3 font-semibold">Severity</th>
                <th className="pb-3 font-semibold">Peer State</th>
                <th className="pb-3 font-semibold">Timestamp</th>
                <th className="pb-3 font-semibold text-right">Payload</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 text-slate-300">
              {events.map((ev) => (
                <tr key={ev.event_id} className="hover:bg-slate-800/30">
                  <td className="py-3 font-mono text-slate-400">#{ev.seq}</td>
                  <td className="py-3 font-mono font-medium text-slate-200">{ev.event_type}</td>
                  <td className="py-3">
                    <span className="px-2 py-0.5 rounded font-mono text-[10px] bg-slate-800 text-slate-300 border border-slate-700">
                      {ev.source}
                    </span>
                  </td>
                  <td className="py-3 text-slate-400 font-mono text-[11px]">
                    {ev.tenant_id} / {ev.ledger_id}
                  </td>
                  <td className="py-3">
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        ev.severity === 'CRITICAL' ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20' :
                        ev.severity === 'ERROR' ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20' :
                        ev.severity === 'WARN' ? 'bg-yellow-500/10 text-yellow-400 border border-yellow-500/20' :
                        'bg-blue-500/10 text-blue-400 border border-blue-500/20'
                      }`}
                    >
                      {ev.severity}
                    </span>
                  </td>
                  <td className="py-3">
                    {ev.published_to_peers ? (
                      <span className="text-emerald-400 font-medium">DISPATCHED</span>
                    ) : (
                      <span className="text-amber-400 font-medium">PENDING</span>
                    )}
                  </td>
                  <td className="py-3 text-slate-400">{new Date(ev.created_at_utc).toLocaleTimeString()}</td>
                  <td className="py-3 text-right">
                    <button
                      onClick={() => setInspectingEvent(ev)}
                      className="p-1 hover:bg-slate-800 rounded text-indigo-400 hover:text-indigo-300"
                      title="Inspect Payload"
                    >
                      <Eye className="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              ))}
              {events.length === 0 && (
                <tr>
                  <td colSpan={8} className="text-center py-8 text-slate-500">
                    No federated events recorded yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Payload Modal */}
      {inspectingEvent && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-xl w-full p-6 space-y-4 shadow-2xl">
            <div className="flex justify-between items-center border-b border-slate-800 pb-3">
              <h3 className="text-base font-semibold text-white flex items-center gap-2">
                <Radio className="w-4 h-4 text-indigo-400" />
                {inspectingEvent.event_type}
              </h3>
              <button
                onClick={() => setInspectingEvent(null)}
                className="text-slate-400 hover:text-slate-200"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="space-y-2 text-xs">
              <div className="text-slate-400 font-mono">Event ID: {inspectingEvent.event_id}</div>
              <div className="text-slate-400 font-mono">Tenant: {inspectingEvent.tenant_id} • Ledger: {inspectingEvent.ledger_id}</div>
            </div>
            <div className="bg-slate-950 p-4 rounded-lg border border-slate-800 overflow-x-auto">
              <pre className="text-xs font-mono text-indigo-300">
                {JSON.stringify(inspectingEvent.payload, null, 2)}
              </pre>
            </div>
            <div className="flex justify-end">
              <button
                onClick={() => setInspectingEvent(null)}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-sm font-medium transition"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Create Tenant Modal */}
      {showTenantModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-6 space-y-4 shadow-2xl">
            <div className="flex justify-between items-center border-b border-slate-800 pb-3">
              <h3 className="text-base font-semibold text-white flex items-center gap-2">
                <PlusCircle className="w-4 h-4 text-indigo-400" />
                Register Federation Tenant
              </h3>
              <button
                onClick={() => setShowTenantModal(false)}
                className="text-slate-400 hover:text-slate-200"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleCreateTenant} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Tenant Identifier
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. tenant_acme_corp"
                  value={newTenantId}
                  onChange={(e) => setNewTenantId(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-indigo-500 font-mono"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Organization Name
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Acme Corporation"
                  value={newTenantName}
                  onChange={(e) => setNewTenantName(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div className="flex justify-end gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setShowTenantModal(false)}
                  className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-sm font-medium transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submittingTenant}
                  className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm font-medium transition disabled:opacity-50"
                >
                  {submittingTenant ? 'Creating...' : 'Create Tenant'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
