# IronLedger Financial Data Guidelines (Cast Iron Charlie extension)

Addendum to the Cast Iron Charlie Design System for financial/ledger UI. Not part of the bound
design system itself (that project is read-only to us) — keep this file as the reference for all
IronLedger screens built in this project.

## Color tokens (new, additive to CICDS palette)
- `--gain: #5a9e6f` / `--gain-bright: #8fc79e` / `--gain-tint: rgba(90,158,111,.1)` — credits, positive deltas, healthy status, approved states.
- `--loss: #b8412f` / `--loss-bright: #e2765f` / `--loss-tint: rgba(184,65,47,.12)` — debits, negative deltas, error/denied states.
- Existing CICDS `--ember`/`--brass` stay reserved for brand accents and neutral highlights (not gain/loss).

## Usage rules
- Amount columns: red/green text only, no background fill, weight 700.
- Status badges (approved/rejected/error/denied): colored border + tint background + bright text, Barlow Condensed, uppercase, letter-spacing .15em.
- Confidence/match scores: gain-bright text, no badge chrome unless flagging low confidence (<70%, use loss-bright).
- Stat blocks: 3px left border in gain/loss/ember, matching low-opacity tint background — mirrors CICDS pull-quote left-border pattern.
- Charts: bars/lines colored by sign (gain green / loss red), never a third neutral color for data.

## Depth & texture treatment
- Cards sit one step lighter than the page background (page `#0d0a08`, card `#1a1410`) with a 1px `rgba(154,144,136,.2)` border and a soft `0 4px 14px rgba(0,0,0,.3)` shadow — avoid black-on-black.
- One soft blurred radial glow per card (`radial-gradient(circle, <accent>,transparent 70%)`, `filter:blur(28–30px)`, ~200–260px, tucked in a corner) — color matches that screen's dominant signal (green for balances/inbox, rust for audit/errors, brass for docs). Always give real content `position:relative;z-index:1` so it paints above the glow.
- Oversized Playfair Display ghost-text watermark (`rgba(139,58,26,.05–.06)`, 70–130px) per screen, one word tied to that screen's function (INBOX, SAFE, AUDIT, LEDGER, GUIDE).
- Gradient-rule dividers (`linear-gradient(to right,transparent,rgba(139,58,26,.4),transparent)`, 1px) between stacked screens instead of plain gaps.

## Typography mapping
- Playfair Display: headline numbers, screen titles, big stat values.
- Libre Baskerville: payee/description text, body copy, italic annotations.
- Barlow Condensed: labels, nav, badges, amounts in dense table contexts, uppercase UI chrome.

Reference build: `IronLedger UI Enhancements.dc.html`.
