
"""Generate and synchronize up-to-date Operator Guide & Technical Reference documentation."""

from __future__ import annotations
from pathlib import Path

DOCS_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>IronLedger Operator Guide &amp; Documentation</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
  <script>
    tailwind.config = {
      darkMode: 'class',
      theme: {
        extend: {
          fontFamily: {
            sans: ['Inter', 'sans-serif'],
            mono: ['"Fira Code"', 'monospace'],
          },
          colors: {
            brand: {
              50: '#eef2ff',
              500: '#6366f1',
              600: '#4f46e5',
              700: '#4338ca',
            },
          }
        }
      }
    }
  </script>
  <style>
    body { background-color: #0b0f19; color: #cbd5e1; }
    .prose-code { font-family: 'Fira Code', monospace; }
    html { scroll-behavior: smooth; }
    ::-webkit-scrollbar { width: 8px; height: 8px; }
    ::-webkit-scrollbar-track { background: #0f172a; }
    ::-webkit-scrollbar-thumb { background: #334155; border-radius: 4px; }
    ::-webkit-scrollbar-thumb:hover { background: #475569; }
  </style>
</head>
<body class="min-h-screen flex flex-col font-sans antialiased text-slate-300 bg-slate-950">
  <header class="sticky top-0 z-50 h-14 bg-slate-900/90 backdrop-blur border-b border-slate-800 px-6 flex items-center justify-between">
    <div class="flex items-center space-x-3">
      <div class="flex items-center justify-center w-8 h-8 rounded bg-indigo-600 text-white font-mono font-bold text-sm shadow-md shadow-indigo-500/20">
        IL
      </div>
      <div>
        <span class="font-bold text-sm tracking-wide text-slate-100 flex items-center gap-2">
          IronLedger
          <span class="text-[10px] px-1.5 py-0.5 rounded bg-indigo-950/80 text-indigo-300 border border-indigo-800 font-mono">
            v0.12.0 &bull; Enterprise Operator Guide
          </span>
        </span>
      </div>
    </div>
    <div class="flex items-center space-x-4 text-xs font-mono">
      <a href="/" class="px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 text-white font-medium flex items-center gap-1.5 shadow transition-colors">
        <span>&larr; Open Operator Workbench</span>
      </a>
    </div>
  </header>

  <div class="flex-1 max-w-7xl w-full mx-auto flex">
    <aside class="w-64 border-r border-slate-800/80 p-6 hidden md:block shrink-0 sticky top-14 h-[calc(100vh-3.5rem)] overflow-y-auto">
      <div class="text-[11px] font-mono uppercase tracking-wider text-slate-500 font-semibold mb-3">Diataxis Framework</div>
      <nav class="space-y-1 text-xs">
        <a href="#tutorial" class="block px-3 py-2 rounded text-slate-300 hover:bg-slate-800/60 hover:text-white transition-colors">1. Quickstart Tutorial</a>
        <ul class="pl-4 space-y-1 text-slate-400 text-[11px]">
          <li><a href="#tutorial-step1" class="hover:text-indigo-400">&bull; Step 1: Ingest Statements</a></li>
          <li><a href="#tutorial-step2" class="hover:text-indigo-400">&bull; Step 2: Review &amp; Approve</a></li>
          <li><a href="#tutorial-step3" class="hover:text-indigo-400">&bull; Step 3: Valuation &amp; Watchlist</a></li>
          <li><a href="#tutorial-step4" class="hover:text-indigo-400">&bull; Step 4: Outbox Federation</a></li>
        </ul>
        <a href="#how-to" class="block px-3 py-2 rounded text-slate-300 hover:bg-slate-800/60 hover:text-white transition-colors pt-2">2. How-To Guides</a>
        <ul class="pl-4 space-y-1 text-slate-400 text-[11px]">
          <li><a href="#how-to-portfolio" class="hover:text-indigo-400">&bull; Multi-Asset Portfolio &amp; Pricing</a></li>
          <li><a href="#how-to-sankey" class="hover:text-indigo-400">&bull; Cash Flow &amp; Sankey Analysis</a></li>
          <li><a href="#how-to-review" class="hover:text-indigo-400">&bull; Staging &amp; Split Postings</a></li>
          <li><a href="#how-to-compliance" class="hover:text-indigo-400">&bull; Compliance Audit Bundles</a></li>
          <li><a href="#how-to-failover" class="hover:text-indigo-400">&bull; HA Failover &amp; Raft Leases</a></li>
        </ul>
        <a href="#reference" class="block px-3 py-2 rounded text-slate-300 hover:bg-slate-800/60 hover:text-white transition-colors pt-2">3. Technical Reference</a>
        <ul class="pl-4 space-y-1 text-slate-400 text-[11px]">
          <li><a href="#ref-api" class="hover:text-indigo-400">&bull; REST API Catalog</a></li>
          <li><a href="#ref-cli" class="hover:text-indigo-400">&bull; CLI Command Matrix</a></li>
          <li><a href="#ref-shortcuts" class="hover:text-indigo-400">&bull; Keyboard Shortcuts</a></li>
        </ul>
        <a href="#explanation" class="block px-3 py-2 rounded text-slate-300 hover:bg-slate-800/60 hover:text-white transition-colors pt-2">4. Architecture &amp; Invariants</a>
        <ul class="pl-4 space-y-1 text-slate-400 text-[11px]">
          <li><a href="#exp-rational" class="hover:text-indigo-400">&bull; Zero-Float Rational Arithmetic</a></li>
          <li><a href="#exp-pricing" class="hover:text-indigo-400">&bull; Dual-Write Price Architecture</a></li>
          <li><a href="#exp-meta-ledger" class="hover:text-indigo-400">&bull; Cryptographic Meta-Ledger</a></li>
        </ul>
      </nav>
    </aside>

    <main class="flex-1 p-6 md:p-10 max-w-4xl overflow-y-auto space-y-14">
      <section class="space-y-4 border-b border-slate-800 pb-8">
        <div class="inline-flex items-center gap-2 px-2.5 py-1 rounded bg-indigo-950/80 border border-indigo-800/60 text-indigo-300 font-mono text-xs">
          <span>Enterprise Operator Guide</span> &bull; <span>v0.12.0</span> &bull; <span>Auto-Synchronized on Build</span>
        </div>
        <h1 class="text-3xl md:text-4xl font-bold tracking-tight text-white">IronLedger Operator Guide &amp; Reference</h1>
        <p class="text-base text-slate-400 leading-relaxed">
          IronLedger is an enterprise financial operating system combining plaintext Beancount accounting authority with SQLite analytical projections, exact-rational multi-asset valuation, compliance Merkle trees, and lease-fenced event streaming.
        </p>
      </section>

      <section id="tutorial" class="space-y-6">
        <div class="flex items-center gap-2 border-b border-slate-800 pb-2">
          <span class="text-xs font-mono px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800 font-bold uppercase">Diataxis 1</span>
          <h2 class="text-2xl font-bold text-white">Quickstart Tutorial</h2>
        </div>
        <div class="space-y-4">
          <div id="tutorial-step1" class="p-4 rounded-lg bg-slate-900 border border-slate-800 space-y-2">
            <h3 class="text-sm font-semibold text-white font-mono">1. Ingest Statement Records</h3>
            <pre class="p-3 rounded bg-slate-950 border border-slate-800 text-xs font-mono text-emerald-300 overflow-x-auto">python -m ironledger.cli import inbox/checking_export.ofx --confirm "import inbox/checking_export.ofx"</pre>
          </div>
          <div id="tutorial-step2" class="p-4 rounded-lg bg-slate-900 border border-slate-800 space-y-2">
            <h3 class="text-sm font-semibold text-white font-mono">2. Review &amp; Approve in Operator Workbench</h3>
            <pre class="p-3 rounded bg-slate-950 border border-slate-800 text-xs font-mono text-emerald-300 overflow-x-auto">python -m ironledger.cli web --port 8000</pre>
          </div>
          <div id="tutorial-step3" class="p-4 rounded-lg bg-slate-900 border border-slate-800 space-y-2">
            <h3 class="text-sm font-semibold text-white font-mono">3. Multi-Asset Watchlist &amp; Portfolio Valuation</h3>
            <pre class="p-3 rounded bg-slate-950 border border-slate-800 text-xs font-mono text-emerald-300 overflow-x-auto">python -m ironledger.cli prices poll --ledger-id default</pre>
          </div>
          <div id="tutorial-step4" class="p-4 rounded-lg bg-slate-900 border border-slate-800 space-y-2">
            <h3 class="text-sm font-semibold text-white font-mono">4. Dispatch Outbox Events</h3>
            <pre class="p-3 rounded bg-slate-950 border border-slate-800 text-xs font-mono text-emerald-300 overflow-x-auto">python -m ironledger.cli federation outbox dispatch --worker-id worker_prod_1 --batch-size 50</pre>
          </div>
        </div>
      </section>

      <section id="how-to" class="space-y-6">
        <div class="flex items-center gap-2 border-b border-slate-800 pb-2">
          <span class="text-xs font-mono px-2 py-0.5 rounded bg-blue-950 text-blue-300 border border-blue-800 font-bold uppercase">Diataxis 2</span>
          <h2 class="text-2xl font-bold text-white">How-To Guides</h2>
        </div>

        <div id="how-to-portfolio" class="p-5 rounded-lg bg-slate-900/60 border border-slate-800 space-y-3">
          <h3 class="text-base font-semibold text-white">How to Manage Multi-Asset Holdings &amp; Watchlist Pricing</h3>
          <ul class="list-disc list-inside text-xs text-slate-300 space-y-1.5 pl-1">
            <li><strong>Watchlist Guard:</strong> In the Workbench <em>Holdings &amp; Watchlist</em> view, click the <strong>Lock Guard</strong> button to toggle edit mode before adding or removing symbols.</li>
            <li><strong>Add Symbols:</strong> Supply base symbol (e.g. <code>NVDA</code>), quote currency (<code>USD</code>), and optional fallback price.</li>
            <li><strong>Remove Symbols:</strong> Click the 🗑 trash button on any unlocked symbol row, or delete from <code>config/prices.json</code>.</li>
            <li><strong>On-Demand Sync:</strong> Click <strong>Sync Watchlist</strong> to scrape live quotes and refresh valuation tables.</li>
          </ul>
        </div>

        <div id="how-to-sankey" class="p-5 rounded-lg bg-slate-900/60 border border-slate-800 space-y-3">
          <h3 class="text-base font-semibold text-white">How to Inspect Cash Flow Sankey Diagrams</h3>
          <p class="text-xs text-slate-400">The Sankey visualizer renders directed cash flow linkages from Income accounts through Operating Buffer to Expenses and Asset allocations for any <code>YYYY-MM</code> period.</p>
        </div>

        <div id="how-to-compliance" class="p-5 rounded-lg bg-slate-900/60 border border-slate-800 space-y-3">
          <h3 class="text-base font-semibold text-white">How to Generate and Verify Compliance Audit Bundles</h3>
          <pre class="p-3 rounded bg-slate-950 text-xs font-mono text-slate-300">python -m ironledger.cli compliance generate --ledger-id default --framework SOC2_TYPE2 --out bundle.tar
python -m ironledger.cli compliance verify --bundle bundle.tar</pre>
        </div>
      </section>

      <section id="reference" class="space-y-6">
        <div class="flex items-center gap-2 border-b border-slate-800 pb-2">
          <span class="text-xs font-mono px-2 py-0.5 rounded bg-purple-950 text-purple-300 border border-purple-800 font-bold uppercase">Diataxis 3</span>
          <h2 class="text-2xl font-bold text-white">Technical Reference</h2>
        </div>

        <div id="ref-api" class="p-5 rounded-lg bg-slate-900/60 border border-slate-800 space-y-3">
          <h3 class="text-base font-semibold text-white">REST API Catalog</h3>
          <table class="w-full text-left font-mono text-xs">
            <thead class="text-slate-500 border-b border-slate-800">
              <tr><th class="py-2">Method</th><th class="py-2">Endpoint</th><th class="py-2">Description</th></tr>
            </thead>
            <tbody class="divide-y divide-slate-800/60 text-slate-300">
              <tr><td class="py-2 text-emerald-400 font-bold">GET</td><td class="py-2 text-indigo-300">/api/analytics/watchlist</td><td class="py-2 text-slate-400">List active watchlist commodities and prices</td></tr>
              <tr><td class="py-2 text-indigo-400 font-bold">POST</td><td class="py-2 text-indigo-300">/api/analytics/watchlist/add</td><td class="py-2 text-slate-400">Add symbol to config/prices.json</td></tr>
              <tr><td class="py-2 text-rose-400 font-bold">DELETE</td><td class="py-2 text-indigo-300">/api/analytics/watchlist/{symbol}</td><td class="py-2 text-slate-400">Remove symbol from watchlist</td></tr>
              <tr><td class="py-2 text-indigo-400 font-bold">POST</td><td class="py-2 text-indigo-300">/api/analytics/prices/sync</td><td class="py-2 text-slate-400">Trigger on-demand feed scraping</td></tr>
              <tr><td class="py-2 text-emerald-400 font-bold">GET</td><td class="py-2 text-indigo-300">/api/analytics/portfolio</td><td class="py-2 text-slate-400">Consolidated multi-asset holdings &amp; P&amp;L</td></tr>
              <tr><td class="py-2 text-emerald-400 font-bold">GET</td><td class="py-2 text-indigo-300">/api/analytics/sankey?period=YYYY-MM</td><td class="py-2 text-slate-400">Directed cash flow link matrix</td></tr>
            </tbody>
          </table>
        </div>

        <div id="ref-cli" class="p-5 rounded-lg bg-slate-900/60 border border-slate-800 space-y-3">
          <h3 class="text-base font-semibold text-white">CLI Command Matrix</h3>
          <pre class="p-3 rounded bg-slate-950 text-xs font-mono text-slate-300 overflow-x-auto">python -m ironledger.cli web --port 8000
python -m ironledger.cli prices poll --ledger-id default
python -m ironledger.cli prices sync --symbols AAPL MSFT BTC
python -m ironledger.cli compile --dry-run
python -m ironledger.cli compile --confirm "authorize compile"</pre>
        </div>

        <div id="ref-shortcuts" class="p-5 rounded-lg bg-slate-900/60 border border-slate-800 space-y-3">
          <h3 class="text-base font-semibold text-white">Keyboard Shortcuts</h3>
          <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs font-mono">
            <div class="p-2 rounded bg-slate-950 border border-slate-800"><kbd class="text-indigo-300 font-bold">j</kbd> Next row</div>
            <div class="p-2 rounded bg-slate-950 border border-slate-800"><kbd class="text-indigo-300 font-bold">k</kbd> Previous row</div>
            <div class="p-2 rounded bg-slate-950 border border-slate-800"><kbd class="text-emerald-300 font-bold">a</kbd> Approve staged</div>
            <div class="p-2 rounded bg-slate-950 border border-slate-800"><kbd class="text-rose-300 font-bold">x</kbd> Reject staged</div>
            <div class="p-2 rounded bg-slate-950 border border-slate-800"><kbd class="text-indigo-300 font-bold">Ctrl+K</kbd> Command Palette</div>
            <div class="p-2 rounded bg-slate-950 border border-slate-800"><kbd class="text-indigo-300 font-bold">Ctrl+R</kbd> Rule Wizard</div>
            <div class="p-2 rounded bg-slate-950 border border-slate-800"><kbd class="text-indigo-300 font-bold">Ctrl+S</kbd> Simulate</div>
            <div class="p-2 rounded bg-slate-950 border border-slate-800"><kbd class="text-indigo-300 font-bold">Ctrl+Enter</kbd> Compile</div>
          </div>
        </div>
      </section>

      <section id="explanation" class="space-y-6">
        <div class="flex items-center gap-2 border-b border-slate-800 pb-2">
          <span class="text-xs font-mono px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800 font-bold uppercase">Diataxis 4</span>
          <h2 class="text-2xl font-bold text-white">Architecture &amp; Invariants</h2>
        </div>
        <div id="exp-rational" class="p-5 rounded-lg bg-slate-900/60 border border-slate-800 space-y-2">
          <h3 class="text-base font-semibold text-white">Zero-Float Exact Rational Arithmetic</h3>
          <p class="text-xs text-slate-400">Enforced by static AST verification: zero float type annotations or float arithmetic in financial calculations. Exact Numerator/Denominator representation guarantees audit reproducibility without IEEE 754 precision drift.</p>
        </div>
      </section>

      <footer class="pt-8 border-t border-slate-800 text-xs text-slate-500 font-mono flex items-center justify-between">
        <div>IronLedger Enterprise Financial Operating System</div>
        <div>Local-first &bull; Beancount + SQLite Authority</div>
      </footer>
    </main>
  </div>
</body>
</html>"""

def build_documentation(target_path: Path | None = None) -> Path:
    repo_root = Path(__file__).resolve().parent.parent
    if target_path is None:
        target_path = repo_root / "web" / "public" / "docs" / "index.html"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(DOCS_HTML_TEMPLATE, encoding="utf-8")
    print(f"Documentation generated at {target_path} ({len(DOCS_HTML_TEMPLATE)} bytes)")
    return target_path

if __name__ == "__main__":
    build_documentation()

