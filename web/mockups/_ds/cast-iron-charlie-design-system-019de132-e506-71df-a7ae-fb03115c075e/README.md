# Cast Iron Charlie — Design System

## Overview

**Cast Iron Charlie** is a feature documentary about Charles Emil Sorensen — the Danish-born Ford Motor Company executive who built the moving assembly line and designed the Willow Run bomber plant. The website at [castironcharlie.com](https://castironcharlie.com) serves as the film's primary promotional presence, with a research archive portal at `/archive`.

**Production company:** Cast Iron Productions LLC (Tampa, FL)  
**Twitter/X:** [@CastFeSorensen](https://x.com/CastFeSorensen)  
**Contact:** info@castironcharlie.com

### Sources

- **GitHub repository:** `sorensencc-dotcom/castironcharlie` (private) — contains two HTML files:
  - `index.html` (~2MB; includes base64-embedded photos) — main marketing site
  - `archive/index.html` (~109KB) — password-gated research archive portal
- No Figma file was provided. Design system has been derived entirely from codebase.

### Products / Surfaces

1. **Main website** (`castironcharlie.com`) — Documentary landing page with hero, story acts, stats, filmmaker bio, timeline, press/media assets, and contact form.
2. **Research Archive** (`castironcharlie.com/archive`) — Password-gated portal for press/researchers to access photographic collections (MFM, Kroll, BGSU, THF).

---

## Content Fundamentals

### Voice & Tone

The copy is **grave, literary, and declarative** — written as if the subject deserves to be taken seriously by history. Think: serious long-form journalism or documentary narration. Sentences are often short and punchy, then followed by longer, more complex elaboration.

**Characteristic patterns:**
- **Em-dash pauses** for drama: *"Denmark sent him. America forgot him."*
- **Parallel construction:** *"He built the moving assembly line, designed Willow Run, and gave America the Jeep."*
- **Understatement and irony:** The subheading "He built the moving assembly line" followed by "America forgot him" — the implied contrast does the emotional work.
- **Active, declarative verbs:** built, designed, gave, produced, turned
- **Dates and statistics used as proof:** "a B-24 Liberator every 63 minutes at its peak"
- Eyebrow labels and section labels are **ALL CAPS, widely spaced** — utilitarian, archival, not expressive

### Person / Perspective
- Website copy is **third person** about Sorensen and the documentary.
- Form copy and labels use **second person** (imperative): "Enter access code", "Request Access →"
- The filmmakers' section uses first-person plural ("we") sparingly

### Casing
- **Section labels / eyebrows:** ALL CAPS with wide letter-spacing (0.2–0.4em)
- **Nav links:** ALL CAPS, condensed, small
- **Body / headings:** Sentence case or Title Case
- **Buttons/CTAs:** ALL CAPS, condensed
- No emoji used anywhere. No exclamation marks in display copy.

### Length & Density
- Headlines are short and cinematic (1–4 words, often with italic em phrase on second line)
- Body paragraphs are ~3–5 sentences, dense with fact
- Section labels appear before almost every heading as an eyebrow

### Examples

> *"He built the moving assembly line, designed Willow Run, and gave America the Jeep. Denmark sent him. America forgot him."*

> *"Charles Emil Sorensen spent four decades as Henry Ford's most trusted lieutenant — the man who turned the moving assembly line from idea into industrial reality."*

---

## Visual Foundations

### Color System

Dark, warm, industrial palette. Almost entirely desaturated brown-blacks, with rust/ember as the only vivid accent. No cool colors. Inspired by forge, iron, rust, ash, brass — the physical materials of the story.

| Token | Hex | Usage |
|-------|-----|-------|
| `--black` | `#0a0806` | Primary background, deepest dark |
| `--forge` | `#1a1410` | Secondary background (sections) |
| `--iron` | `#2c2420` | Tertiary background (raised surfaces) |
| `--rust` | `#8B3A1A` | Hover state for ember, subtle accents |
| `--ember` | `#C4501A` | Primary accent — section labels, borders, CTAs |
| `--brass` | `#B8922A` | Secondary accent — logo, italic highlights, key images |
| `--ash` | `#9a9088` | Secondary text, labels, captions, muted UI |
| `--bone` | `#e8e0d4` | Body text, primary readable content |
| `--paper` | `#f2ece2` | Lightest warm white (used rarely) |
| `--white` | `#faf6f0` | Headings on dark, hero title |

**Accent color philosophy:** Ember (`#C4501A`) is the primary interactive signal — it appears on section labels, borders of interactive cards, CTAs, form focus states. Brass (`#B8922A`) is reserved for the brand name/logo and italicized headline phrases, giving it more prestige.

### Typography

Three typefaces, each with a distinct role:

**Playfair Display** (Google Fonts) — *Serif Display*
- Weights: 400, 700, 900; also italic 400/700
- Used for: All major headings, hero title, pull quotes, blockquotes, act titles, timeline titles
- Notable: `font-weight: 900` italic for brand name in footer; `font-style: italic` + `color: var(--brass)` for the second line of hero titles

**Libre Baskerville** (Google Fonts) — *Serif Body*
- Weights: 400, 700; italic 400
- Used for: All body copy, form inputs, pull-quote blockquotes
- The default `body` font — grounded, readable, serious

**Barlow Condensed** (Google Fonts) — *Sans-Serif Label / UI*
- Weights: 300, 400, 600, 700, 800
- Used for: ALL navigation, ALL section labels/eyebrows, ALL buttons/CTAs, ALL stat numbers, ALL metadata labels, logo
- Uppercase with wide letter-spacing (0.2–0.4em) — the "utility" layer of the typographic system

### Backgrounds & Texture

- **Film grain overlay:** A fixed SVG-based `fractalNoise` filter applied as `body::before` — creates period-appropriate film grain texture across all backgrounds. Opacity 0.4.
- **Large ghost text:** Section headers have oversized `::before` pseudo-elements with text like "ARCHIVE", "MFM", "KROLL" in the background at near-invisible opacity (`rgba(139,58,26,0.04)`) — gives depth without visual noise.
- **Background gradient on hero:** Dual linear-gradient — dark-to-transparent from bottom (for text legibility) and left-edge vignette.
- **Photo treatment:** `filter: sepia(20%) contrast(1.05) brightness(0.9)` applied to all images — maintains a warm, period-documentary aesthetic.
- **Horizontal rule:** Not a plain `<hr>` — uses `background: linear-gradient(to right, transparent, rgba(139,58,26,0.4), transparent)` — the ember color fades in/out horizontally.

### Spacing & Layout

- Section inner containers: `max-width: 1100px`, `margin: 0 auto`, `padding: 7rem 4rem`
- Section inner padding scales down at mobile: `padding: 5rem 2rem`
- Card gaps: `1.5rem` (tight grid) to `5–6rem` (wide editorial grid)
- No border-radius anywhere — all corners are **sharp (0px)**. This is a defining visual trait.

### Cards & Surfaces

- Cards use `border: 1px solid rgba(154,144,136,0.12)` at rest — very subtle, almost invisible
- Hover state: `border-color: rgba(196,80,26,0.4)` — ember tint appears
- Card backgrounds: `rgba(26,20,16,0.6)` — forge color at 60% opacity
- **No border-radius, no box-shadow** — stark, flat surfaces, differentiated only by border color and background tint

### Borders

- Section dividers: `1px solid rgba(139,58,26,0.2)` — rust/ember at low opacity
- Interactive borders: ember color at various opacities (0.2 idle, 0.4–0.5 hover)
- Left-border accent (pull quotes, stats): `3px solid var(--ember)` with `rgba(139,58,26,0.06)` background tint
- Section labels have a short `::after` rule: `max-width: 60px; height: 1px; background: var(--ember)`

### Animations

- **Entry animation:** `fadeUp` — `opacity: 0 → 1`, `translateY(30px → 0)`, 1s ease, staggered by 0.3s on hero elements
- **Scroll indicator:** `scrollPulse` — opacity 0.4 → 1 → 0.4, 2s infinite
- **Hover transitions:** `transition: 0.2–0.3s` on color, border-color, background, transform
- **Press/hover on CTA buttons:** `transform: translateY(-2px)` — subtle lift (not scale)
- **Image hover:** `transform: scale(1.04–1.05)` with `transition: 0.5s ease` — slow, cinematic zoom
- **No spring/bounce animations** — everything is ease or ease-in-out, cinematic

### Hover & Press States

- Links: `color: var(--ash) → var(--white)` on hover
- CTA buttons: `background: var(--ember) → var(--rust)` + `translateY(-2px)`
- Cards: border-color darkens to ember tint
- Images: slow scale + filter desaturation removed

### Corner Radii

**Zero. Everywhere.** No `border-radius` anywhere in the codebase. This is intentional and distinctive.

### Navigation

- Fixed, full-width top nav
- `background: linear-gradient(to bottom, rgba(10,8,6,0.95), transparent)` — fades to transparent when at top
- `nav.scrolled` class adds: `background: rgba(10,8,6,0.97)` — solid on scroll
- Logo: Barlow Condensed 800, letter-spacing 0.25em, brass color
- Links: Barlow Condensed 400, 0.8rem, letter-spacing 0.2em, ash color → white hover
- Mobile: hamburger → full-screen overlay drawer with large (1.6rem) links

### Imagery

- All photography: historical B&W or sepia archival photos
- Filter: `sepia(20%) contrast(1.05) brightness(0.9)` — warm, aged
- Hero image: `object-position: center 30%` — crops to upper portion
- Captions: Barlow Condensed, 0.65rem, letter-spacing 0.25em, uppercase, ash color

---

## Iconography

No icon font or icon library is used anywhere. The brand intentionally avoids decorative iconography. Instead:

- **Em-dashes (—)** serve as the only "bullet" or list marker (`urgency-list li::before { content: '—' }`)
- **Arrow character (→)** is used in CTAs and links inline (not as an icon element)
- **Scroll indicator** is a 1px vertical line + animated `span` — no SVG icon
- Navigation "hamburger" is pure CSS: three `span` elements morphing with `transform`
- Status badges use a bullet character (`●`) in colored text: `● Live`
- Star (★) appears as a Unicode character for "key image" labels

**No SVG icons, no icon fonts, no emoji, no png icons exist in the codebase.** This is a deliberate aesthetic choice — the brand communicates through typography, color, and space rather than iconography.

Substitutions: None needed. The zero-icon approach is part of the brand identity.

---

## File Index

```
README.md                     — This file
SKILL.md                      — Agent skill descriptor (Claude Code compatible)
colors_and_type.css           — All CSS custom properties + semantic type classes

assets/
  (no external logo/image files found in repo — all photography is
   base64-embedded in the HTML source files)

preview/                      — Design System tab cards (700px wide)
  colors-primary.html         — 10-color base palette swatches
  colors-semantic.html        — Semantic usage map (bg, fg, border, status)
  type-display.html           — Playfair Display: hero, H1–H4, italic, pull quote
  type-body.html              — Libre Baskerville: lead, body, bold, caption
  type-ui.html                — Barlow Condensed: logo, nav, label, CTA, stats
  spacing-tokens.html         — Spacing scale sp-1–sp-16, max-width, section padding
  spacing-borders.html        — Border + divider system (gradient rule, card states)
  components-buttons.html     — Button variants: primary, hover, disabled, text, form
  components-cards.html       — Card states: default, hover, brass key-image
  components-forms.html       — Form inputs: text, focus, error, select, textarea
  components-nav.html         — Nav: transparent top, solid scrolled, archive variant
  components-badges.html      — Status badges, priority tags, tier overlays, nav badge
  components-sections.html    — Section label eyebrow, pull quote, stat blocks, ghost text
  brand-texture.html          — Film grain, background levels, hero gradient overlay

ui_kits/
  website/
    README.md                 — UI kit overview + screen list
    index.html                — Interactive prototype: main site + archive portal
    Nav.jsx                   — Navigation (transparent/scrolled/mobile drawer)
    Hero.jsx                  — Hero section with staggered animations
    SectionComponents.jsx     — Shared: SectionLabel, PullQuote, StatBlock, GradientRule,
                                Tag, StatusBadge, SectionInner
    ContentSections.jsx       — HookSection, StorySection, WillysSection, WhyNowSection,
                                TimelineSection, PressSection, ContactSection, Footer
    ArchivePage.jsx           — Archive portal: collection cards, password modal,
                                MFM photo series grid with filters, lightbox viewer
```

### Quick Start

To use this design system in a new HTML prototype:
1. Import Google Fonts (Playfair Display, Libre Baskerville, Barlow Condensed)
2. Link `colors_and_type.css` for all CSS vars and utility classes
3. Copy the relevant JSX components from `ui_kits/website/` as a starting point
4. Reference `README.md` for tone, copy style, and visual rules
