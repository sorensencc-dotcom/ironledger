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
    <div className="space-y-6 font-mono relative">
      {/* Top Header & Actions */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 bg-[#1a1410] border border-[#2c2420] p-6 rounded-none shadow-lg relative overflow-hidden">
        <div className="ghost-watermark text-[6rem] -top-8 -right-4 select-none pointer-events-none">
          FEDERATION
        </div>

        <div className="relative z-10">
          <div className="flex items-center gap-3">
            <Network className="w-7 h-7 text-[#b8922a]" />
            <h1 className="text-2xl font-serif font-bold text-[#f2ece2] tracking-tight">
              Multi-Tenant Federation & Event Routing
            </h1>
            <span className="px-2.5 py-0.5 rounded-none text-xs font-bold font-mono bg-[#241c16] text-[#b8922a] border border-[#3a2e26]">
              gov.event.v1
            </span>
          </div>
          <p className="text-sm text-[#7a6e65] mt-1 font-sans">
            Cross-cluster audit propagation, tenant domain isolation, and outbox event streaming.
          </p>
        </div>

        <div className="flex items-center gap-3 relative z-10">
          <button
            onClick={() => setShowTenantModal(true)}
            className="flex items-center gap-2 px-3.5 py-2 bg-[#c4501a] hover:bg-[#d4622b] text-[#f2ece2] rounded-none text-xs font-mono uppercase font-bold transition shadow-md"
          >
            <PlusCircle className="w-4 h-4" />
            Add Tenant
          </button>
          <button
            onClick={loadData}
            disabled={loading}
            className="p-2 bg-[#1a1410] hover:bg-[#241c16] text-[#e8dfd1] rounded-none text-xs font-mono uppercase transition border border-[#3a2e26]"
            title="Refresh"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin text-[#c4501a]' : 'text-[#b8922a]'}`} />
          </button>
        </div>
      </div>

      {/* Cluster Nodes & Tenant Domains Top Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Tenant Registry Cards */}
        <div className="bg-[#1a1410] border border-[#2c2420] rounded-none p-5 shadow-none relative overflow-hidden">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Layers className="w-5 h-5 text-[#b8922a]" />
              <h2 className="text-xs font-bold text-[#b8922a] font-sans uppercase tracking-wider">
                Tenant Domains ({tenants.length})
              </h2>
            </div>
            <select
              value={selectedTenant}
              onChange={(e) => setSelectedTenant(e.target.value)}
              className="bg-[#0d0a08] text-[#f2ece2] text-xs rounded-none px-2 py-1 border border-[#3a2e26] focus:outline-none focus:border-[#c4501a] font-mono"
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
                className="flex items-center justify-between p-3 rounded-none bg-[#130f0c] border border-[#2c2420]"
              >
                <div>
                  <div className="text-sm font-serif font-bold text-[#f2ece2]">{t.name}</div>
                  <div className="text-xs text-[#7a6e65] font-mono">id: {t.tenant_id} • ledger: {t.default_ledger_id}</div>
                </div>
                <span className="flex items-center gap-1.5 px-2 py-0.5 rounded-none text-[10px] font-bold font-mono bg-[#132a1c] text-[#8fc79e] border border-[#1d442b]">
                  <CheckCircle2 className="w-3 h-3" />
                  Active
                </span>
              </div>
            ))}
            {tenants.length === 0 && (
              <div className="text-center py-6 text-xs text-[#7a6e65]">No tenants registered</div>
            )}
          </div>
        </div>

        {/* Peer Cluster Topologies */}
        <div className="lg:col-span-2 bg-[#1a1410] border border-[#2c2420] rounded-none p-5 shadow-none relative overflow-hidden">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Server className="w-5 h-5 text-[#b8922a]" />
              <h2 className="text-xs font-bold text-[#b8922a] font-sans uppercase tracking-wider">
                Cluster Node Topology ({nodes.length})
              </h2>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-[#7a6e65] border-b border-[#2c2420] font-sans font-bold text-[10px] uppercase tracking-wider">
                <tr>
                  <th className="pb-2">Node ID</th>
                  <th className="pb-2">Cluster</th>
                  <th className="pb-2">Role</th>
                  <th className="pb-2">Endpoint URL</th>
                  <th className="pb-2">Heartbeat</th>
                  <th className="pb-2">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#2c2420]/60 text-[#a89e94]">
                {nodes.map((node) => (
                  <tr key={node.node_id} className="hover:bg-[#241c16]/50">
                    <td className="py-2.5 font-mono font-bold text-[#f2ece2]">{node.node_id}</td>
                    <td className="py-2.5">{node.cluster_id}</td>
                    <td className="py-2.5">
                      <span className={`px-2 py-0.5 rounded-none font-mono text-[10px] font-bold ${
                        node.role === 'PRIMARY' ? 'bg-[#2a1d0d] text-[#e0a84c] border border-[#4a3518]' :
                        node.role === 'REPLICA' ? 'bg-[#241c16] text-[#b8922a] border border-[#3a2e26]' :
                        'bg-[#2c1a14] text-[#c4501a] border border-[#c4501a]'
                      }`}>
                        {node.role}
                      </span>
                    </td>
                    <td className="py-2.5 font-mono text-[#7a6e65] truncate max-w-[180px]">{node.endpoint_url}</td>
                    <td className="py-2.5 text-[#7a6e65]">{node.last_heartbeat_utc ? new Date(node.last_heartbeat_utc).toLocaleTimeString() : 'N/A'}</td>
                    <td className="py-2.5">
                      <span className="flex items-center gap-1 text-[#8fc79e] font-bold font-mono">
                        <span className="w-1.5 h-1.5 rounded-none bg-[#8fc79e] animate-pulse"></span>
                        ONLINE
                      </span>
                    </td>
                  </tr>
                ))}
                {nodes.length === 0 && (
                  <tr>
                    <td colSpan={6} className="text-center py-6 text-[#7a6e65]">
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
      <div className="bg-[#1a1410] border border-[#2c2420] rounded-none p-6 shadow-none relative overflow-hidden">
        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-5">
          <div className="flex items-center gap-2">
            <Radio className="w-5 h-5 text-[#b8922a]" />
            <h2 className="text-base font-serif font-bold text-[#f2ece2]">
              Federated Governance Event Stream (gov.event.v1)
            </h2>
          </div>

          <div className="flex items-center gap-3">
            <label className="text-xs text-[#7a6e65] uppercase font-sans font-bold text-[10px]">Source:</label>
            <select
              value={selectedSource}
              onChange={(e) => setSelectedSource(e.target.value)}
              className="bg-[#0d0a08] text-[#f2ece2] text-xs rounded-none px-2 py-1 border border-[#3a2e26] focus:outline-none focus:border-[#c4501a] font-mono"
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
            <thead className="text-[#7a6e65] border-b border-[#2c2420] uppercase tracking-wider text-[10px] font-sans font-bold">
              <tr>
                <th className="pb-3">Seq</th>
                <th className="pb-3">Event Type</th>
                <th className="pb-3">Source</th>
                <th className="pb-3">Tenant / Ledger</th>
                <th className="pb-3">Severity</th>
                <th className="pb-3">Peer State</th>
                <th className="pb-3">Timestamp</th>
                <th className="pb-3 text-right">Payload</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#2c2420]/60 text-[#a89e94]">
              {events.map((ev) => (
                <tr key={ev.event_id} className="hover:bg-[#241c16]/50">
                  <td className="py-3 font-mono text-[#7a6e65]">#{ev.seq}</td>
                  <td className="py-3 font-mono font-bold text-[#f2ece2]">{ev.event_type}</td>
                  <td className="py-3">
                    <span className="px-2 py-0.5 rounded-none font-mono text-[10px] bg-[#241c16] text-[#b8922a] border border-[#3a2e26]">
                      {ev.source}
                    </span>
                  </td>
                  <td className="py-3 text-[#7a6e65] font-mono text-[11px]">
                    {ev.tenant_id} / {ev.ledger_id}
                  </td>
                  <td className="py-3">
                    <span
                      className={`px-2 py-0.5 rounded-none text-[10px] font-bold font-mono ${
                        ev.severity === 'CRITICAL' ? 'bg-[#2c120e] text-[#e2765f] border border-[#4a1c14]' :
                        ev.severity === 'ERROR' ? 'bg-[#2c120e] text-[#e2765f] border border-[#4a1c14]' :
                        ev.severity === 'WARN' ? 'bg-[#2a1d0d] text-[#e0a84c] border border-[#4a3518]' :
                        'bg-[#241c16] text-[#b8922a] border border-[#3a2e26]'
                      }`}
                    >
                      {ev.severity}
                    </span>
                  </td>
                  <td className="py-3">
                    {ev.published_to_peers ? (
                      <span className="text-[#8fc79e] font-bold font-mono">DISPATCHED</span>
                    ) : (
                      <span className="text-[#e0a84c] font-bold font-mono">PENDING</span>
                    )}
                  </td>
                  <td className="py-3 text-[#7a6e65]">{new Date(ev.created_at_utc).toLocaleTimeString()}</td>
                  <td className="py-3 text-right">
                    <button
                      onClick={() => setInspectingEvent(ev)}
                      className="p-1 hover:bg-[#241c16] rounded-none text-[#b8922a] hover:text-[#f2ece2] transition-colors"
                      title="Inspect Payload"
                    >
                      <Eye className="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              ))}
              {events.length === 0 && (
                <tr>
                  <td colSpan={8} className="text-center py-8 text-[#7a6e65]">
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
        <div className="fixed inset-0 bg-black/75 backdrop-blur-md flex items-center justify-center p-4 z-50 select-none">
          <div className="bg-[#1a1410] border border-[#3a2e26] rounded-none max-w-xl w-full p-6 space-y-4 shadow-2xl relative overflow-hidden">
            <div className="ghost-watermark text-[5rem] -top-6 -right-4 select-none pointer-events-none">
              EVENT
            </div>

            <div className="flex justify-between items-center border-b border-[#2c2420] pb-3 relative z-10">
              <h3 className="text-base font-serif font-bold text-[#f2ece2] flex items-center gap-2">
                <Radio className="w-4 h-4 text-[#b8922a]" />
                {inspectingEvent.event_type}
              </h3>
              <button
                onClick={() => setInspectingEvent(null)}
                className="text-[#7a6e65] hover:text-[#f2ece2] transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="space-y-2 text-xs relative z-10 font-mono">
              <div className="text-[#7a6e65]">Event ID: <span className="text-[#f2ece2]">{inspectingEvent.event_id}</span></div>
              <div className="text-[#7a6e65]">Tenant: <span className="text-[#b8922a]">{inspectingEvent.tenant_id}</span> • Ledger: <span className="text-[#b8922a]">{inspectingEvent.ledger_id}</span></div>
            </div>
            <div className="bg-[#0d0a08] p-4 rounded-none border border-[#2c2420] overflow-x-auto relative z-10">
              <pre className="text-xs font-mono text-[#8fc79e]">
                {JSON.stringify(inspectingEvent.payload, null, 2)}
              </pre>
            </div>
            <div className="flex justify-end relative z-10">
              <button
                onClick={() => setInspectingEvent(null)}
                className="px-4 py-2 bg-[#1a1410] hover:bg-[#241c16] text-[#e8dfd1] border border-[#3a2e26] rounded-none text-xs font-mono uppercase tracking-wider transition"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Create Tenant Modal */}
      {showTenantModal && (
        <div className="fixed inset-0 bg-black/75 backdrop-blur-md flex items-center justify-center p-4 z-50 select-none">
          <div className="bg-[#1a1410] border border-[#3a2e26] rounded-none max-w-md w-full p-6 space-y-4 shadow-2xl relative overflow-hidden">
            <div className="ghost-watermark text-[5rem] -top-6 -right-4 select-none pointer-events-none">
              TENANT
            </div>

            <div className="flex justify-between items-center border-b border-[#2c2420] pb-3 relative z-10">
              <h3 className="text-base font-serif font-bold text-[#f2ece2] flex items-center gap-2">
                <PlusCircle className="w-4 h-4 text-[#b8922a]" />
                Register Federation Tenant
              </h3>
              <button
                onClick={() => setShowTenantModal(false)}
                className="text-[#7a6e65] hover:text-[#f2ece2] transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleCreateTenant} className="space-y-4 relative z-10">
              <div>
                <label className="block text-[10px] font-sans font-bold uppercase tracking-wider text-[#a89e94] mb-1">
                  Tenant Identifier
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. tenant_acme_corp"
                  value={newTenantId}
                  onChange={(e) => setNewTenantId(e.target.value)}
                  className="w-full bg-[#0d0a08] border border-[#3a2e26] rounded-none px-3 py-2 text-xs text-[#f2ece2] focus:outline-none focus:border-[#c4501a] font-mono"
                />
              </div>

              <div>
                <label className="block text-[10px] font-sans font-bold uppercase tracking-wider text-[#a89e94] mb-1">
                  Organization Name
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Acme Corporation"
                  value={newTenantName}
                  onChange={(e) => setNewTenantName(e.target.value)}
                  className="w-full bg-[#0d0a08] border border-[#3a2e26] rounded-none px-3 py-2 text-xs text-[#f2ece2] focus:outline-none focus:border-[#c4501a] font-mono"
                />
              </div>

              <div className="flex justify-end gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setShowTenantModal(false)}
                  className="px-3.5 py-1.5 bg-[#1a1410] hover:bg-[#241c16] text-[#7a6e65] hover:text-[#f2ece2] border border-[#3a2e26] rounded-none text-xs font-mono uppercase transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submittingTenant}
                  className="px-4 py-1.5 bg-[#c4501a] hover:bg-[#d4622b] text-[#f2ece2] rounded-none text-xs font-mono uppercase font-bold transition disabled:opacity-50"
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
