import { Inbox, BookOpen, Layers, Shield, Plug, Webhook, BarChart3, Network, ShieldAlert } from 'lucide-react';

export type ActiveView =
  | 'staging'
  | 'rules'
  | 'balances'
  | 'audit'
  | 'connectors'
  | 'webhooks'
  | 'metrics'
  | 'federation'
  | 'failover'
  | 'settings';


interface SidebarProps {
  activeView: ActiveView;
  onSelectView: (view: ActiveView) => void;
  pendingCount: number;
  rulesCount: number;
  dlqCount?: number;
}

export const Sidebar: React.FC<SidebarProps> = ({
  activeView,
  onSelectView,
  pendingCount,
  rulesCount,
  dlqCount = 0,
}) => {
  const navItems = [
    {
      id: 'staging' as ActiveView,
      label: 'Staging Inbox',
      icon: Inbox,
      badge: pendingCount > 0 ? pendingCount : null,
      badgeColor: 'bg-indigo-600 text-white',
    },
    {
      id: 'connectors' as ActiveView,
      label: 'Connectors & Ingestion',
      icon: Plug,
    },
    {
      id: 'webhooks' as ActiveView,
      label: 'Webhooks & DLQ',
      icon: Webhook,
      badge: dlqCount > 0 ? dlqCount : null,
      badgeColor: 'bg-rose-600 text-white',
    },
    {
      id: 'federation' as ActiveView,
      label: 'Federation & Events',
      icon: Network,
    },
    {
      id: 'failover' as ActiveView,
      label: 'Failover & Cluster HA',
      icon: ShieldAlert,
    },
    {
      id: 'metrics' as ActiveView,
      label: 'Telemetry & Metrics',
      icon: BarChart3,
    },
    {
      id: 'rules' as ActiveView,
      label: 'Rule Engine',
      icon: BookOpen,
      badge: rulesCount > 0 ? rulesCount : null,
      badgeColor: 'bg-slate-700 text-slate-300',
    },
    {
      id: 'balances' as ActiveView,
      label: 'Balances & Chart',
      icon: Layers,
    },
    {
      id: 'audit' as ActiveView,
      label: 'Meta-Ledger Audit',
      icon: Shield,
    },
  ];


  return (
    <aside className="w-60 border-r border-slate-700 bg-slate-900/95 flex flex-col justify-between shrink-0 select-none">
      <div className="p-3 space-y-1">
        <div className="px-3 py-2 text-[10px] font-mono tracking-wider text-slate-500 uppercase">
          Navigation
        </div>
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = activeView === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onSelectView(item.id)}
              className={`w-full flex items-center justify-between px-3 py-2 rounded text-xs font-medium transition-colors ${
                isActive
                  ? 'bg-indigo-600/20 text-indigo-300 border border-indigo-600/30 font-semibold'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
              }`}
            >
              <div className="flex items-center space-x-2.5">
                <Icon className={`w-4 h-4 ${isActive ? 'text-indigo-400' : 'text-slate-400'}`} />
                <span>{item.label}</span>
              </div>
              {item.badge !== null && item.badge !== undefined && (
                <span
                  className={`text-[10px] font-mono px-1.5 py-0.2 rounded-full font-bold ${
                    item.badgeColor
                  }`}
                >
                  {item.badge}
                </span>
              )}
            </button>
          );
        })}
      </div>

      <div className="p-3 border-t border-slate-800 font-mono text-[11px] text-slate-500 flex items-center justify-between">
        <span>SQLite + Beancount</span>
        <span className="text-emerald-400">● LIVE</span>
      </div>
    </aside>
  );
};
