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
      badgeColor: 'border border-ember/40 bg-ember/10 text-ember',
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
      badgeColor: 'border border-border bg-black/40 text-ash',
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
      badgeColor: 'border border-loss/40 bg-loss-tint text-loss-bright',
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
    <div className="space-y-1 mb-5">
      <div className="px-3 py-1 font-ui text-[10px] tracking-[0.25em] text-rust uppercase flex items-center gap-2">
        <span>{title}</span>
        <span className="flex-1 max-w-[30px] h-[1px] bg-rust/40 inline-block" />
      </div>
      {items.map((item) => {
        const Icon = item.icon;
        const isActive = activeView === item.id;
        return (
          <button
            key={item.id}
            onClick={() => onSelectView(item.id)}
            className={`w-full flex items-center justify-between px-3 py-2 text-xs font-serif transition-colors ${
              isActive
                ? 'bg-[rgba(139,58,26,0.08)] text-white border-l-2 border-ember font-bold pl-2.5'
                : 'text-ash hover:text-bone hover:bg-card-hover'
            }`}
          >
            <div className="flex items-center space-x-2.5">
              <Icon className={`w-3.5 h-3.5 ${isActive ? 'text-ember' : 'text-ash'}`} />
              <span className="text-[13px]">{item.label}</span>
            </div>
            {item.badge !== null && item.badge !== undefined && (
              <span
                className={`text-[10px] font-ui tracking-wider px-1.5 py-0.5 border font-bold ${
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
    <aside className="w-60 border-r border-[rgba(154,144,136,0.12)] bg-[#140f0c] flex flex-col justify-between shrink-0 select-none h-[calc(100vh-3.5rem)]">
      <div className="p-3 overflow-y-auto flex-1 min-h-0">
        {renderNavGroup('Navigation', financialNav)}
        {renderNavGroup('Platform & Cluster', platformNav)}
      </div>

      <div className="p-3 border-t border-[rgba(154,144,136,0.12)] font-ui text-[11px] tracking-wider uppercase text-ash flex items-center justify-between shrink-0 bg-[#100c0a]">
        <span>SQLite + Beancount</span>
        <span className="text-gain-bright font-bold">● LIVE</span>
      </div>
    </aside>
  );
};
