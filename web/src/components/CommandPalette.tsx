import React, { useEffect, useState } from 'react';
import { Search, Play, RefreshCw, Shield, Layers, Inbox, BookOpen } from 'lucide-react';
import type { ActiveView } from './Sidebar';

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
  onSelectView: (view: ActiveView) => void;
  onSimulate: () => void;
  onCompile: () => void;
}

export const CommandPalette: React.FC<CommandPaletteProps> = ({
  isOpen,
  onClose,
  onSelectView,
  onSimulate,
  onCompile,
}) => {
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);

  const actions = [
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
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-start justify-center pt-24 p-4 font-sans select-none">
      <div className="w-full max-w-xl bg-slate-900 border border-slate-700 rounded-lg shadow-2xl overflow-hidden">
        {/* Search Header */}
        <div className="px-4 py-3 border-b border-slate-800 flex items-center gap-3">
          <Search className="w-4 h-4 text-slate-400" />
          <input
            type="text"
            placeholder="Type a command or search action..."
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIndex(0);
            }}
            autoFocus
            className="flex-1 bg-transparent text-sm text-slate-100 placeholder-slate-500 focus:outline-none font-mono"
          />
          <kbd className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">
            ESC
          </kbd>
        </div>

        {/* Action List */}
        <div className="max-h-72 overflow-y-auto p-2 divide-y divide-slate-800/40">
          {filtered.length === 0 ? (
            <div className="p-6 text-center text-xs text-slate-500 font-mono">
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
                  className={`w-full px-3 py-2 rounded text-left flex items-center justify-between text-xs transition-colors ${
                    isSel ? 'bg-indigo-600/30 text-indigo-200 border border-indigo-500/40 font-medium' : 'text-slate-300 hover:bg-slate-800/60'
                  }`}
                >
                  <div className="flex items-center space-x-2.5">
                    <Icon className={`w-4 h-4 ${isSel ? 'text-indigo-400' : 'text-slate-400'}`} />
                    <span>{action.title}</span>
                  </div>
                  <span className="text-[10px] font-mono text-slate-500 uppercase">{action.category}</span>
                </button>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
};

