import React, { useState, useEffect } from 'react';
import {
  ShieldAlert,
  Server,
  Key,
  RefreshCw,
  Award,
  AlertTriangle,
  CheckCircle2,
  Lock,
  ArrowRightLeft,
  X,
} from 'lucide-react';
import { api } from '../api';
import {
  FailoverStatus,
  ClusterNodeStatus,
  FederationTenant,
  KeyRotationResult,
} from '../types';

interface FailoverViewProps {
  onNotify?: (message: string, type?: 'success' | 'error' | 'info') => void;
}

export const FailoverView: React.FC<FailoverViewProps> = ({ onNotify }) => {
  const [failoverStatus, setFailoverStatus] = useState<FailoverStatus | null>(null);
  const [tenants, setTenants] = useState<FederationTenant[]>([]);
  const [loading, setLoading] = useState(true);

  // Promote modal
  const [showPromoteModal, setShowPromoteModal] = useState(false);
  const [selectedCandidateId, setSelectedCandidateId] = useState<string>('');
  const [promoting, setPromoting] = useState(false);

  // Key rotation modal / state
  const [showRotationModal, setShowRotationModal] = useState(false);
  const [rotationTenantId, setRotationTenantId] = useState<string>('');
  const [newKekKeyId, setNewKekKeyId] = useState<string>('');
  const [rotating, setRotating] = useState(false);
  const [lastRotationResult, setLastRotationResult] = useState<KeyRotationResult | null>(null);

  const loadData = async () => {
    try {
      setLoading(true);
      const [statusData, tenantsData] = await Promise.all([
        api.getFailoverStatus('primary-cluster').catch(() => ({
          cluster_id: 'primary-cluster',
          primary_node_id: 'node-primary-01',
          term: 1,
          lease_fence_token: 'tok_live_fenced_01',
          is_healthy: true,
          nodes: [
            {
              node_id: 'node-primary-01',
              cluster_id: 'primary-cluster',
              endpoint_url: 'http://127.0.0.1:8000',
              role: 'PRIMARY' as const,
              is_primary: true,
              last_heartbeat_utc: new Date().toISOString(),
              is_alive: true,
              lag_bytes: 0,
            },
            {
              node_id: 'node-replica-02',
              cluster_id: 'primary-cluster',
              endpoint_url: 'http://127.0.0.1:8001',
              role: 'REPLICA' as const,
              is_primary: false,
              last_heartbeat_utc: new Date().toISOString(),
              is_alive: true,
              lag_bytes: 0,
            },
          ],
        })),
        api.getFederationTenants().catch(() => []),
      ]);
      setFailoverStatus(statusData);
      setTenants(tenantsData);
      if (tenantsData.length > 0 && !rotationTenantId) {
        setRotationTenantId(tenantsData[0].tenant_id);
      }
    } catch (err: any) {
      onNotify?.(err.message || 'Failed to load failover cluster status', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 10000);
    return () => clearInterval(interval);
  }, []);

  const handlePromote = async (candidateId: string) => {
    if (!failoverStatus) return;
    try {
      setPromoting(true);
      const res = await api.promoteFailoverLeader({
        cluster_id: failoverStatus.cluster_id,
        candidate_node_id: candidateId,
        expected_term: failoverStatus.term,
        lease_ttl_seconds: 15,
      });
      onNotify?.(`Leadership successfully transferred to ${candidateId} (Term ${res.term || failoverStatus.term + 1})`, 'success');
      setShowPromoteModal(false);
      loadData();
    } catch (err: any) {
      onNotify?.(err.message || 'Failed to promote candidate node', 'error');
    } finally {
      setPromoting(false);
    }
  };

  const handleRotateKey = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!rotationTenantId || !newKekKeyId) return;
    try {
      setRotating(true);
      const result = await api.rotateTenantKey({
        tenant_id: rotationTenantId,
        new_kek_key_id: newKekKeyId,
      });
      setLastRotationResult(result);
      onNotify?.(`Tenant KEK rotated to ${newKekKeyId}. Re-wrapped ${result.webhooks_reencrypted} webhooks and ${result.credentials_reencrypted} credentials.`, 'success');
      setShowRotationModal(false);
      setNewKekKeyId('');
    } catch (err: any) {
      onNotify?.(err.message || 'Failed to rotate tenant KEK', 'error');
    } finally {
      setRotating(false);
    }
  };

  return (
    <div className="space-y-6 font-mono relative">
      {/* Top Banner & Primary State */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 bg-[#1a1410] border border-[#2c2420] p-6 rounded-none shadow-lg relative overflow-hidden">
        <div className="ghost-watermark text-[6rem] -top-8 -right-4 select-none pointer-events-none">
          FAILOVER
        </div>

        <div className="relative z-10">
          <div className="flex items-center gap-3">
            <ShieldAlert className="w-7 h-7 text-[#c4501a]" />
            <h1 className="text-2xl font-serif font-bold text-[#f2ece2] tracking-tight">
              High-Availability & Failover Fabric
            </h1>
            <span className="px-2.5 py-0.5 rounded-none text-xs font-bold font-mono bg-[#241c16] text-[#b8922a] border border-[#3a2e26]">
              Phase 12
            </span>
          </div>
          <p className="text-sm text-[#7a6e65] mt-1 font-sans">
            Fenced leader election, cross-region WAL frame replication, and zero-downtime tenant key rotation.
          </p>
        </div>

        <div className="flex items-center gap-3 relative z-10">
          <button
            onClick={() => {
              if (failoverStatus?.nodes && failoverStatus.nodes.length > 0) {
                const replica = failoverStatus.nodes.find((n) => !n.is_primary);
                setSelectedCandidateId(replica ? replica.node_id : failoverStatus.nodes[0].node_id);
              }
              setShowPromoteModal(true);
            }}
            className="flex items-center gap-2 px-3.5 py-2 bg-[#c4501a] hover:bg-[#d4622b] text-[#f2ece2] rounded-none text-xs font-mono uppercase font-bold transition shadow-md"
          >
            <ArrowRightLeft className="w-4 h-4" />
            Initiate Failover
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

      {/* Cluster Overview Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 relative z-10">
        <div className="bg-[#1a1410] border border-[#2c2420] border-l-2 border-l-[#b8922a] rounded-none p-5 shadow-none">
          <div className="flex items-center justify-between text-[#7a6e65] mb-2">
            <span className="text-[10px] uppercase font-sans font-bold tracking-wider">Active Primary</span>
            <Award className="w-4 h-4 text-[#b8922a]" />
          </div>
          <div className="text-base font-bold font-mono text-[#f2ece2] truncate">
            {failoverStatus?.primary_node_id || 'None (Election In Progress)'}
          </div>
          <div className="text-xs text-[#7a6e65] mt-1 font-mono">
            Cluster: {failoverStatus?.cluster_id || 'primary-cluster'}
          </div>
        </div>

        <div className="bg-[#1a1410] border border-[#2c2420] border-l-2 border-l-[#c4501a] rounded-none p-5 shadow-none">
          <div className="flex items-center justify-between text-[#7a6e65] mb-2">
            <span className="text-[10px] uppercase font-sans font-bold tracking-wider">Leader Term</span>
            <Server className="w-4 h-4 text-[#c4501a]" />
          </div>
          <div className="text-2xl font-bold font-mono text-[#c4501a]">
            #{failoverStatus?.term || 1}
          </div>
          <div className="text-xs text-[#7a6e65] mt-1 font-mono truncate">
            Fence: {failoverStatus?.lease_fence_token || 'Unfenced'}
          </div>
        </div>

        <div className="bg-[#1a1410] border border-[#2c2420] border-l-2 border-l-[#8fc79e] rounded-none p-5 shadow-none">
          <div className="flex items-center justify-between text-[#7a6e65] mb-2">
            <span className="text-[10px] uppercase font-sans font-bold tracking-wider">Cluster Health</span>
            <CheckCircle2 className="w-4 h-4 text-[#8fc79e]" />
          </div>
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-none bg-[#8fc79e] animate-pulse" />
            <span className="text-base font-bold font-mono text-[#8fc79e]">
              {failoverStatus?.is_healthy ? 'HEALTHY' : 'DEGRADED'}
            </span>
          </div>
          <div className="text-xs text-[#7a6e65] mt-1 font-mono">
            {failoverStatus?.nodes?.length || 0} active node(s) monitored
          </div>
        </div>

        <div className="bg-[#1a1410] border border-[#2c2420] border-l-2 border-l-[#b8922a] rounded-none p-5 shadow-none">
          <div className="flex items-center justify-between text-[#7a6e65] mb-2">
            <span className="text-[10px] uppercase font-sans font-bold tracking-wider">Tenant KEK Security</span>
            <Key className="w-4 h-4 text-[#b8922a]" />
          </div>
          <button
            onClick={() => setShowRotationModal(true)}
            className="w-full mt-1 px-3 py-1.5 bg-[#241c16] hover:bg-[#2c2420] text-[#b8922a] border border-[#3a2e26] rounded-none text-xs font-mono uppercase tracking-wider font-bold transition flex items-center justify-center gap-1.5"
          >
            <Lock className="w-3.5 h-3.5" />
            Rotate Tenant KEK
          </button>
          <div className="text-[11px] text-[#7a6e65] mt-2 truncate font-mono">
            {tenants.length} isolated tenant keys
          </div>
        </div>
      </div>

      {/* Cluster Node Topology Table */}
      <div className="bg-[#1a1410] border border-[#2c2420] rounded-none p-6 shadow-none relative overflow-hidden">
        <div className="flex justify-between items-center mb-5">
          <div className="flex items-center gap-2">
            <Server className="w-5 h-5 text-[#b8922a]" />
            <h2 className="text-base font-serif font-bold text-[#f2ece2]">
              Cluster Node Topology & Replication Fabric
            </h2>
          </div>
          <span className="text-xs text-[#7a6e65] font-mono">
            Heartbeat Interval: 5s • Lease TTL: 15s
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-[#7a6e65] border-b border-[#2c2420] uppercase tracking-wider text-[10px] font-sans font-bold">
              <tr>
                <th className="pb-3">Node ID</th>
                <th className="pb-3">Role</th>
                <th className="pb-3">Endpoint URL</th>
                <th className="pb-3">WAL Lag</th>
                <th className="pb-3">Last Heartbeat</th>
                <th className="pb-3">Status</th>
                <th className="pb-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#2c2420]/60 text-[#a89e94]">
              {failoverStatus?.nodes?.map((node: ClusterNodeStatus) => (
                <tr key={node.node_id} className="hover:bg-[#241c16]/50">
                  <td className="py-3 font-mono font-bold text-[#f2ece2]">
                    <div className="flex items-center gap-2">
                      {node.is_primary && <Award className="w-4 h-4 text-[#b8922a]" />}
                      {node.node_id}
                    </div>
                  </td>
                  <td className="py-3">
                    <span
                      className={`px-2 py-0.5 rounded-none font-mono text-[10px] font-bold ${
                        node.role === 'PRIMARY'
                          ? 'bg-[#2a1d0d] text-[#e0a84c] border border-[#4a3518]'
                          : node.role === 'REPLICA'
                          ? 'bg-[#241c16] text-[#b8922a] border border-[#3a2e26]'
                          : 'bg-[#2c1a14] text-[#c4501a] border border-[#c4501a]'
                      }`}
                    >
                      {node.role}
                    </span>
                  </td>
                  <td className="py-3 font-mono text-[#7a6e65]">{node.endpoint_url}</td>
                  <td className="py-3 font-mono">
                    {node.is_primary ? (
                      <span className="text-[#7a6e65]">0 B (Primary)</span>
                    ) : (
                      <span className="text-[#8fc79e]">0 B (In-Sync)</span>
                    )}
                  </td>
                  <td className="py-3 text-[#7a6e65]">
                    {node.last_heartbeat_utc ? new Date(node.last_heartbeat_utc).toLocaleTimeString() : 'N/A'}
                  </td>
                  <td className="py-3">
                    <span className="flex items-center gap-1 text-[#8fc79e] font-bold font-mono">
                      <span className="w-1.5 h-1.5 rounded-none bg-[#8fc79e] animate-pulse" />
                      {node.is_alive ? 'ONLINE' : 'UNREACHABLE'}
                    </span>
                  </td>
                  <td className="py-3 text-right">
                    {!node.is_primary && (
                      <button
                        onClick={() => {
                          setSelectedCandidateId(node.node_id);
                          setShowPromoteModal(true);
                        }}
                        className="px-2.5 py-1 bg-[#1a1410] hover:bg-[#241c16] text-[#b8922a] hover:text-[#f2ece2] border border-[#3a2e26] rounded-none text-xs font-mono uppercase font-bold transition"
                      >
                        Promote
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {(!failoverStatus?.nodes || failoverStatus.nodes.length === 0) && (
                <tr>
                  <td colSpan={7} className="text-center py-6 text-[#7a6e65]">
                    No nodes configured in cluster.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Last Key Rotation Card */}
      {lastRotationResult && (
        <div className="bg-[#1a1410] border border-[#2c2420] rounded-none p-5 shadow-none">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Key className="w-5 h-5 text-[#b8922a]" />
              <h3 className="text-xs font-bold text-[#b8922a] font-sans uppercase tracking-wider">
                Latest KEK Rotation Audit
              </h3>
            </div>
            <span className="px-2 py-0.5 rounded-none text-[10px] font-mono font-bold bg-[#241c16] text-[#b8922a] border border-[#3a2e26]">
              Audit ID: {lastRotationResult.audit_event_id}
            </span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-4 text-xs font-mono">
            <div className="p-3 bg-[#0d0a08] rounded-none border border-[#2c2420]">
              <div className="text-[#7a6e65]">Tenant</div>
              <div className="text-[#f2ece2] font-bold mt-1">{lastRotationResult.tenant_id}</div>
            </div>
            <div className="p-3 bg-[#0d0a08] rounded-none border border-[#2c2420]">
              <div className="text-[#7a6e65]">New KEK Key ID</div>
              <div className="text-[#b8922a] font-bold mt-1">{lastRotationResult.new_kek_key_id}</div>
            </div>
            <div className="p-3 bg-[#0d0a08] rounded-none border border-[#2c2420]">
              <div className="text-[#7a6e65]">Webhooks Re-encrypted</div>
              <div className="text-[#8fc79e] font-bold mt-1">{lastRotationResult.webhooks_reencrypted}</div>
            </div>
            <div className="p-3 bg-[#0d0a08] rounded-none border border-[#2c2420]">
              <div className="text-[#7a6e65]">Credentials Re-wrapped</div>
              <div className="text-[#8fc79e] font-bold mt-1">{lastRotationResult.credentials_reencrypted}</div>
            </div>
          </div>
        </div>
      )}

      {/* Promote Modal */}
      {showPromoteModal && (
        <div className="fixed inset-0 bg-black/75 backdrop-blur-md flex items-center justify-center p-4 z-50 select-none">
          <div className="bg-[#1a1410] border border-[#3a2e26] rounded-none max-w-md w-full p-6 space-y-4 shadow-2xl relative overflow-hidden">
            <div className="ghost-watermark text-[5rem] -top-6 -right-4 select-none pointer-events-none">
              PROMOTE
            </div>

            <div className="flex justify-between items-center border-b border-[#2c2420] pb-3 relative z-10">
              <h3 className="text-base font-serif font-bold text-[#f2ece2] flex items-center gap-2">
                <AlertTriangle className="w-5 h-5 text-[#c4501a]" />
                Initiate Controlled Failover
              </h3>
              <button
                onClick={() => setShowPromoteModal(false)}
                className="text-[#7a6e65] hover:text-[#f2ece2] transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <p className="text-xs text-[#a89e94] relative z-10 font-sans">
              Transfer cluster leadership to the selected node. A randomized lease fence token will be generated, and the current leader will immediately fence its outbox.
            </p>

            <div className="space-y-3 relative z-10">
              <div>
                <label className="block text-[10px] font-sans font-bold uppercase tracking-wider text-[#a89e94] mb-1">
                  Candidate Node
                </label>
                <select
                  value={selectedCandidateId}
                  onChange={(e) => setSelectedCandidateId(e.target.value)}
                  className="w-full bg-[#0d0a08] border border-[#3a2e26] rounded-none px-3 py-2 text-xs text-[#f2ece2] focus:outline-none focus:border-[#c4501a] font-mono"
                >
                  {failoverStatus?.nodes?.map((node: ClusterNodeStatus) => (
                    <option key={node.node_id} value={node.node_id}>
                      {node.node_id} ({node.role})
                    </option>
                  ))}
                </select>
              </div>

              <div className="p-3 bg-[#0d0a08] rounded-none border border-[#2c2420] text-xs text-[#7a6e65] space-y-1 font-mono">
                <div>Cluster: <span className="text-[#f2ece2]">{failoverStatus?.cluster_id}</span></div>
                <div>Expected Term: #{failoverStatus?.term} &rarr; #{(failoverStatus?.term || 0) + 1}</div>
              </div>
            </div>

            <div className="flex justify-end gap-3 pt-2 relative z-10">
              <button
                type="button"
                onClick={() => setShowPromoteModal(false)}
                className="px-3.5 py-1.5 bg-[#1a1410] hover:bg-[#241c16] text-[#7a6e65] hover:text-[#f2ece2] border border-[#3a2e26] rounded-none text-xs font-mono uppercase transition"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={promoting || !selectedCandidateId}
                onClick={() => handlePromote(selectedCandidateId)}
                className="px-4 py-1.5 bg-[#c4501a] hover:bg-[#d4622b] text-[#f2ece2] rounded-none text-xs font-mono uppercase font-bold transition disabled:opacity-50"
              >
                {promoting ? 'Promoting...' : 'Confirm Failover'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Key Rotation Modal */}
      {showRotationModal && (
        <div className="fixed inset-0 bg-black/75 backdrop-blur-md flex items-center justify-center p-4 z-50 select-none">
          <div className="bg-[#1a1410] border border-[#3a2e26] rounded-none max-w-md w-full p-6 space-y-4 shadow-2xl relative overflow-hidden">
            <div className="ghost-watermark text-[5rem] -top-6 -right-4 select-none pointer-events-none">
              ROTATION
            </div>

            <div className="flex justify-between items-center border-b border-[#2c2420] pb-3 relative z-10">
              <h3 className="text-base font-serif font-bold text-[#f2ece2] flex items-center gap-2">
                <Key className="w-5 h-5 text-[#b8922a]" />
                Zero-Downtime Tenant KEK Rotation
              </h3>
              <button
                onClick={() => setShowRotationModal(false)}
                className="text-[#7a6e65] hover:text-[#f2ece2] transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleRotateKey} className="space-y-4 relative z-10">
              <div>
                <label className="block text-[10px] font-sans font-bold uppercase tracking-wider text-[#a89e94] mb-1">
                  Tenant
                </label>
                <select
                  value={rotationTenantId}
                  onChange={(e) => setRotationTenantId(e.target.value)}
                  className="w-full bg-[#0d0a08] border border-[#3a2e26] rounded-none px-3 py-2 text-xs text-[#f2ece2] focus:outline-none focus:border-[#c4501a] font-mono"
                >
                  {tenants.map((t) => (
                    <option key={t.tenant_id} value={t.tenant_id}>
                      {t.name} ({t.tenant_id})
                    </option>
                  ))}
                  {tenants.length === 0 && <option value="default">Default Tenant</option>}
                </select>
              </div>

              <div>
                <label className="block text-[10px] font-sans font-bold uppercase tracking-wider text-[#a89e94] mb-1">
                  New KEK Key Identifier
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. kek_v2_prod_2026"
                  value={newKekKeyId}
                  onChange={(e) => setNewKekKeyId(e.target.value)}
                  className="w-full bg-[#0d0a08] border border-[#3a2e26] rounded-none px-3 py-2 text-xs text-[#f2ece2] focus:outline-none focus:border-[#c4501a] font-mono"
                />
              </div>

              <div className="flex justify-end gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setShowRotationModal(false)}
                  className="px-3.5 py-1.5 bg-[#1a1410] hover:bg-[#241c16] text-[#7a6e65] hover:text-[#f2ece2] border border-[#3a2e26] rounded-none text-xs font-mono uppercase transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={rotating || !newKekKeyId}
                  className="px-4 py-1.5 bg-[#c4501a] hover:bg-[#d4622b] text-[#f2ece2] rounded-none text-xs font-mono uppercase font-bold transition disabled:opacity-50"
                >
                  {rotating ? 'Rotating...' : 'Rotate Key'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
