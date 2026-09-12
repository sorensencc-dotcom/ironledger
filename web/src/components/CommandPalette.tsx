import React, { useEffect, useState } from 'react';
import { Search, Play, RefreshCw, Shield, Layers, Inbox, BookOpen, HelpCircle, Landmark, TrendingUp, PieChart } from 'lucide-react';
import type { ActiveView } from './Sidebar';

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
  onSelectView: (view: ActiveView) => void;
  onSimulate: () => void;
  onCompile: () => void;
  onSync?: () => void;
}

export const CommandPalette: React.FC<CommandPaletteProps> = ({
  isOpen,
  onClose,
  onSelectView,
  onSimulate,
  onCompile,
  onSync,
}) => {
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);

  const actions = [
    {
      id: 'open-docs',
      title: 'Open User Guide & Documentation (Diataxis)',
      category: 'Documentation',
      icon: HelpCircle,
      run: () => {
        window.open('/docs/index.html', '_blank');
        onClose();
      },
    },
    {
      id: 'goto-staging',
      title: 'Go to Staging Inbox',
      category: 'Navigation',
      icon: Inbox,
      run: () => {
        onSelectView('staging');
        onClose();
      },
    },
    {
      id: 'goto-analytics',
      title: 'View Cash Flow (Sankey)',
      category: 'Navigation',
      icon: TrendingUp,
      run: () => {
        onSelectView('analytics');
        onClose();
      },
    },
    {
      id: 'goto-portfolio',
      title: 'Inspect Investment Portfolio',
      category: 'Navigation',
      icon: PieChart,
      run: () => {
        onSelectView('portfolio');
        onClose();
      },
    },
    {
      id: 'goto-rules',
      title: 'Go to Rule Engine',
      category: 'Navigation',
      icon: BookOpen,
      run: () => {
        onSelectView('rules');
        onClose();
      },
    },
    {
      id: 'goto-balances',
      title: 'Go to Balances & Accounts',
      category: 'Navigation',
      icon: Layers,
      run: () => {
        onSelectView('balances');
        onClose();
      },
    },
    {
      id: 'goto-audit',
      title: 'Go to Meta-Ledger Audit Trail',
      category: 'Navigation',
      icon: Shield,
      run: () => {
        onSelectView('audit');
        onClose();
      },
    },
    {
      id: 'filter-pending',
      title: 'Filter Staging: Pending Only',
      category: 'Filters',
      icon: Inbox,
      run: () => {
        onSelectView('staging');
        onClose();
      },
    },
    {
      id: 'run-sync',
      title: 'Trigger SimpleFIN Bank Synchronization (/api/sync/poll)',
      category: 'Actions',
      icon: Landmark,
      run: () => {
        if (onSync) onSync();
        onClose();
      },
    },
    {
      id: 'run-simulate',
      title: 'Run Safe Mode Dry-Run Simulation',
      category: 'Actions',
      icon: Play,
      run: () => {
        onSimulate();
        onClose();
      },
    },
    {
      id: 'run-compile',
      title: 'Trigger Ledger Compilation & Projection Rebuild',
      category: 'Actions',
      icon: RefreshCw,
      run: () => {
        onCompile();
        onClose();
      },
    },
  ];

  const filtered = actions.filter((a) =>
    a.title.toLowerCase().includes(query.toLowerCase()) ||
    a.category.toLowerCase().includes(query.toLowerCase())
  );

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        if (isOpen) onClose();
      }
      if (!isOpen) return;

      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedIndex((prev) => Math.min(filtered.length - 1, prev + 1));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedIndex((prev) => Math.max(0, prev - 1));
      } else if (e.key === 'Enter') {
        e.preventDefault();
        const action = filtered[selectedIndex];
        if (action) action.run();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, filtered, selectedIndex, onClose]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/75 backdrop-blur-md z-50 flex items-start justify-center pt-24 p-4 font-sans select-none">
      <div className="w-full max-w-xl bg-[#1a1410] border border-[#3a2e26] rounded-none shadow-2xl overflow-hidden relative">
        {/* Ghost Watermark */}
        <div className="ghost-watermark text-[5rem] -top-6 -right-4 select-none pointer-events-none">
          COMMAND
        </div>

        {/* Search Header */}
        <div className="px-4 py-3.5 border-b border-[#2c2420] flex items-center gap-3 bg-[#241c16] relative z-10">
          <Search className="w-4 h-4 text-[#b8922a]" />
          <input
            type="text"
            placeholder="Type a command or search action..."
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIndex(0);
            }}
            autoFocus
            className="flex-1 bg-transparent text-xs text-[#f2ece2] placeholder-[#7a6e65] focus:outline-none font-mono"
          />
          <kbd className="text-[10px] font-mono px-2 py-0.5 rounded-none bg-[#1a1410] text-[#b8922a] border border-[#3a2e26]">
            ESC
          </kbd>
        </div>

        {/* Action List */}
        <div className="max-h-72 overflow-y-auto p-2 divide-y divide-[#2c2420]/60 relative z-10">
          {filtered.length === 0 ? (
            <div className="p-6 text-center text-xs text-[#7a6e65] font-mono">
              No matching commands found.
            </div>
          ) : (
            filtered.map((action, idx) => {
              const Icon = action.icon;
              const isSel = idx === selectedIndex;
              return (
                <button
                  key={action.id}
                  onClick={() => action.run()}
                  className={`w-full px-3 py-2.5 rounded-none text-left flex items-center justify-between text-xs transition-colors ${
                    isSel
                      ? 'bg-[#2c1a14] text-[#f2ece2] border-l-2 border-[#c4501a] font-medium'
                      : 'text-[#a89e94] hover:bg-[#241c16] hover:text-[#f2ece2]'
                  }`}
                >
                  <div className="flex items-center space-x-2.5">
                    <Icon className={`w-4 h-4 ${isSel ? 'text-[#c4501a]' : 'text-[#7a6e65]'}`} />
                    <span className="font-mono text-xs">{action.title}</span>
                  </div>
                  <span className="text-[10px] font-sans font-bold text-[#b8922a] uppercase tracking-wider">
                    {action.category}
                  </span>
                </button>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
};

