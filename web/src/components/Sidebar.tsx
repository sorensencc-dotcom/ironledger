import React from 'react';
import {
  Inbox,
  BookOpen,
  Layers,
  Shield,
  Plug,
  Webhook,
  BarChart3,
  Network,
  ShieldAlert,
  TrendingUp,
  PieChart,
} from 'lucide-react';

export type ActiveView =
  | 'staging'
  | 'rules'
  | 'balances'
  | 'analytics'
  | 'portfolio'
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
  const financialNav = [
    {
      id: 'staging' as ActiveView,
      label: 'Staging Inbox',
      icon: Inbox,
      badge: pendingCount > 0 ? pendingCount : null,
      badgeColor: 'bg-indigo-600 text-white',
    },
    {
      id: 'portfolio' as ActiveView,
      label: 'Portfolio & Watchlist',
      icon: PieChart,
    },
    {
      id: 'analytics' as ActiveView,
      label: 'Cash Flow (Sankey)',
      icon: TrendingUp,
    },
    {
      id: 'balances' as ActiveView,
      label: 'Balances & Chart',
      icon: Layers,
    },
    {
      id: 'rules' as ActiveView,
      label: 'Rule Engine',
      icon: BookOpen,
      badge: rulesCount > 0 ? rulesCount : null,
      badgeColor: 'bg-slate-700 text-slate-300',
    },
  ];

  const platformNav = [
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
      id: 'audit' as ActiveView,
      label: 'Meta-Ledger Audit',
      icon: Shield,
    },
  ];

  const renderNavGroup = (title: string, items: typeof financialNav) => (
    <div className="space-y-1 mb-4">
      <div className="px-3 py-1.5 text-[10px] font-mono tracking-wider text-slate-500 uppercase">
        {title}
      </div>
      {items.map((item) => {
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
  );

  return (
    <aside className="w-60 border-r border-slate-700 bg-slate-900/95 flex flex-col justify-between shrink-0 select-none h-[calc(100vh-3.5rem)]">
      <div className="p-3 overflow-y-auto flex-1 min-h-0">
        {renderNavGroup('Ledger & Valuation', financialNav)}
        {renderNavGroup('Platform & Cluster', platformNav)}
      </div>

      <div className="p-3 border-t border-slate-800 font-mono text-[11px] text-slate-500 flex items-center justify-between shrink-0 bg-slate-900">
        <span>SQLite + Beancount</span>
        <span className="text-emerald-400 font-semibold">● LIVE</span>
      </div>
    </aside>
  );
};
