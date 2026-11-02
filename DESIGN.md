# DESIGN.md — Visual Contract & Design System
**Project:** CBA Asset & Inventory Management System (CBA IMS)  
**Institution:** College of Business Administration  
**Audience:** University administrators, department chairs, property custodians, faculty, and administrative staff  
**Version:** 3.0  
**Status:** Authoritative Visual Contract (Loan Desk direction below supersedes earlier colour, type and component rules)  

---

## Current direction: Loan Desk (v3.0)

Version 3.0 replaces the colours, type and component rules below. The accessibility, RBAC, HTMX, Alpine, scanner and print safeguards in sections 7 and 8 still apply.

- **Idea:** a university equipment library. Manila card, navy ink, red date stamps, ruled lines, index tabs.
- **Tokens:** `static/css/register.css`, loaded last on every page.
  Paper `#f5e9c8`, sheet `#fff8e4`, tab `#e9d8a6`, ink `#16294d`, stamp red `#b8261b`, available green `#2f5d27`, repair amber `#7a4b00`.
- **Type:** Libre Caslon Text for headings, Public Sans for everything else. No third family.
- **Sizes:** body 18 to 20px, nothing under 16px. Buttons at least 52px, form fields at least 56px.
- **Art:** engraved plates in `static/img/plates/`, printed with `mix-blend-mode: multiply`. Icons in buttons stay as Bootstrap Icons.
- **Filters:** index tabs joined to a sheet. Status is a stamped word. Condition is a plain word.
- **Spacing classes:** Bootstrap has no half steps. Do not use `gap-1.5`, `me-1.5` or similar.

## 1. Design Philosophy & Aesthetic Identity

The CBA Asset & Inventory Management System is an internal institutional administrative platform and operational workspace. It is engineered for high-frequency inventory tracking, accountability audits, asset transfers, and equipment borrowing.

### Core Tenets
1. **Modern Workspace, Not Traditional Dashboard or SaaS Slop:** The interface reflects a contemporary, calm, and lightweight product workspace (comparable to modern CRM, database, or analytics systems) adapted for university administrative rigor. It avoids both 2010s-era heavy enterprise portals and consumer-SaaS cliches (no purple/cyan gradients, no floating glassmorphism, no bubble pills, no empty marketing whitespace).
2. **Dense, Legible, and Purposeful:** University property officers handle extensive datasets with long property tags, serial numbers, and custodian records. High information density with strict tabular discipline takes precedence over oversized decorative components.
3. **Monochromatic Ground with Deliberate Accent:** A calm, light neutral foundation (light neutral sidebar, white cards, subtle neutral borders) keeps the workspace low-glare and legible. Saturated color is never used as large decorative card fills. Primary institutional blue (`#1d4ed8`) is reserved for primary actions, active navigation states, and focus rings.
4. **Guardrails without Blandness (Anti-Slop Alignment):** Anti-Slop rules serve as strict architectural guardrails against generic AI-generated aesthetics, decorative noise, and visual clutter. They do not dictate an ugly, flat, or uncrafted interface. The modern workspace direction provides the positive craft: deliberate spatial rhythm, hairline borders, refined micro-radii, and precise typographic hierarchy.
5. **Operational Resiliency & Viewport Parity:** Full operational fidelity across desktop (1280px+), laptop/tablet (768px–1024px), and mobile devices (360px–480px), guaranteeing rapid floor audits and barcode/QR scanner workflows.

---

## 2. Color Palette & Functional Token System

All color tokens adhere strictly to WCAG 2.1 AA standards (minimum contrast ratio of 4.5:1 for body copy and 3:1 for graphical/UI controls).

### 2.1 Canvas, Surface & Shell Tokens
| Token Name | Hex Code | Purpose & Usage | Contrast vs Text |
| :--- | :--- | :--- | :--- |
| `--cba-canvas-bg` | `#f8fafc` | Slate 50: Global application background and canvas | Base canvas |
| `--cba-surface-card` | `#ffffff` | Pure White: Primary containers, cards, tables, modal bodies, form panels | Base surface |
| `--cba-surface-subtle` | `#f1f5f9` | Slate 100: Table header backgrounds, read-only field fills, secondary containers | 1.15:1 vs White |
| `--cba-surface-hover` | `#f8fafc` | Subtle row and interactive item hover state | Subtle feedback |
| `--cba-sidebar-bg` | `#f8fafc` | Slate 50: Light neutral sidebar canvas (replaces old dark `#0f172a`) | Base chrome |
| `--cba-sidebar-border` | `#e2e8f0` | Slate 200: Hairline 1px right sidebar divider | Structure |
| `--cba-topbar-bg` | `#ffffff` | Pure White: Top navigation header surface | Base chrome |
| `--cba-topbar-border` | `#e2e8f0` | Slate 200: Hairline 1px bottom topbar divider | Structure |
| `--cba-border-subtle` | `#e2e8f0` | Slate 200: Default component outlines, table row dividers, card borders | Structure |
| `--cba-border-medium` | `#cbd5e1` | Slate 300: Form field borders, tab dividers, interactive controls | Structure |
| `--cba-border-focus` | `#2563eb` | Blue 600: Active focused input border | Focus state |

### 2.2 Primary Brand & Interactive Tokens
| Token Name | Hex Code | Purpose & Usage | Contrast vs White |
| :--- | :--- | :--- | :--- |
| `--cba-primary` | `#1d4ed8` | Modern Institutional Blue: Primary CTAs, active links, brand accents | 7.3:1 (Passes AAA Large, AA Body) |
| `--cba-primary-hover` | `#1e40af` | Darker Blue: Primary button hover/pressed states | 9.0:1 |
| `--cba-primary-light` | `#eff6ff` | Blue 50: Active nav pill background, selected table rows, active filters | Surface tint |
| `--cba-focus-ring` | `rgba(37,99,235,0.18)` | Crisp 3px box-shadow glow around focused interactive controls | High visibility |
| `--cba-danger` | `#dc2626` | Red 600: Destructive actions (Delete, Write-off, Deactivate) | 4.6:1 |
| `--cba-danger-hover` | `#b91c1c` | Red 700: Destructive action hover state | 6.0:1 |
| `--cba-focus-ring-danger` | `rgba(220,38,38,0.18)` | 3px box-shadow glow for destructive focus states | High visibility |

### 2.3 Text & Typography Tokens
| Token Name | Hex Code | Purpose & Usage | Contrast vs White |
| :--- | :--- | :--- | :--- |
| `--cba-text-primary` | `#0f172a` | Slate 900: Primary headings, data figures, body copy, table cell data | 15.6:1 |
| `--cba-text-secondary` | `#475569` | Slate 600: Secondary text, table headers, breadcrumbs, descriptions | 5.8:1 |
| `--cba-text-muted` | `#64748b` | Slate 500: Metadata timestamps, footnote annotations, placeholder text | 4.6:1 |
| `--cba-text-inverted` | `#ffffff` | Pure White: Text on solid primary and danger buttons | 21:1 |
| `--cba-sidebar-text` | `#475569` | Slate 600: Resting navigation item label | 5.8:1 |
| `--cba-sidebar-text-active` | `#1d4ed8` | Blue 700: Active navigation item label | 7.3:1 |

### 2.4 Semantic & Status Tokens
> Saturated colors are strictly functional indicators. They are never used as full background fills for cards or panel headers. Badges and alerts always follow the formula: subtle background tint + 1px border accent + dark semantic text.

| State | Background Tint | Border Accent | Text / Icon Color | Semantic Meaning |
| :--- | :--- | :--- | :--- | :--- |
| **Available / Healthy / Approved** | `#f0fdf4` (Emerald 50) | `#bbf7d0` (Emerald 200) | `#166534` (Emerald 800) | Asset available for deployment, approved transfer/request, stock healthy |
| **Warning / Maintenance / Low Stock**| `#fffbeb` (Amber 50) | `#fde68a` (Amber 200) | `#92400e` (Amber 800) | Low supply threshold, pending approval, scheduled maintenance |
| **Critical / Damaged / Overdue** | `#fef2f2` (Red 50) | `#fecaca` (Red 200) | `#991b1b` (Red 800) | Damaged asset, overdue loan, rejected transfer, missing item |
| **Assigned / In Circulation** | `#eff6ff` (Blue 50) | `#bfdbfe` (Blue 200) | `#1e40af` (Blue 800) | Asset deployed to faculty/staff, active borrowing, active transfer |
| **Archived / Disposed / Retired** | `#f8fafc` (Slate 50) | `#e2e8f0` (Slate 200) | `#475569` (Slate 600) | Written-off, retired, historical, or inactive record |

---

## 3. Typography Architecture

Typography prioritizes rapid vertical scanning, numeric data alignment, and compact administrative density.

### 3.1 Typeface Stack
- **Primary Interface Font:** `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`
- **Tabular / Monospace Font:** `\"SFMono-Regular\", Consolas, \"Liberation Mono\", Menlo, monospace` (mandatory for Asset Tags, Serial Numbers, Barcodes, Audit Timestamps, and Currency/Quantities with `font-variant-numeric: tabular-nums`).

### 3.2 Scale & Hierarchy
| Level | Font Size | Line Height | Font Weight | Letter Spacing | Context / Usage |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `H1` | `1.375rem` (22px) | `1.3` | `700` | `-0.015em` | Top-level section titles, primary page headers |
| `H2` | `1.1875rem` (19px) | `1.35` | `600` | `-0.01em` | Panel titles, modal headers, major section groupings |
| `H3` | `1.0625rem` (17px) | `1.4` | `600` | `0` | Sub-panel headers, card group titles |
| `Body` | `0.875rem` (14px) | `1.5` | `400` | `0` | Standard body text, table cell data, form labels |
| `Body Small` | `0.8125rem` (13px) | `1.4` | `400` | `0` | Metadata, helper text, breadcrumbs, table footers |
| `Micro / Eyebrow` | `0.6875rem` (11px)| `1.2` | `600` | `0.05em` | Status badges, category labels, uppercase table headers |
| `Metric Value` | `1.625rem` (26px) | `1.2` | `700` | `-0.02em` | Metric stat numbers (clean tabular digits, max 26px) |

---

## 4. Spacing, Layout Grid & Elevation

### 4.1 Spacing Scale (4px/8px Geometric Rhythm)
- `space-1`: `4px` (tight button padding, icon-text gap)
- `space-2`: `8px` (badge padding, table cell vertical padding, compact form gaps)
- `space-3`: `12px` (standard container internal padding on mobile, form field spacing)
- `space-4`: `16px` (card internal padding, desktop table cell horizontal padding)
- `space-5`: `20px` (standard main layout padding on desktop)
- `space-6`: `24px` (grid column gaps, section dividers)
- `space-8`: `32px` (page section separation)

### 4.2 Borders & Radii (Modern Workspace Scale)
- **Content Panels & Cards:** `8px` (`0.5rem`)
- **Buttons & Form Inputs:** `6px` (`0.375rem`)
- **Badges, Micro Chips & Code Tags:** `4px` (`0.25rem`) with 1px border
- **Table Outlines:** `1px solid var(--cba-border-subtle)`
- **Pill Shapes (`9999px`):** Reserved exclusively for interactive filter tags, avatar chips, and search badges. Never use pill shapes for standard buttons or operational data cards.

### 4.3 Restrained Shadows & Elevation
Elevation relies primarily on hairline borders (`1px solid #e2e8f0`). Shadows are subtle and functional:
- **Resting Card:** `0 1px 2px 0 rgba(0, 0, 0, 0.04)`
- **Hover / Interactive Card:** `0 2px 4px -1px rgba(0, 0, 0, 0.06)`
- **Dropdown & Popover:** `0 4px 6px -1px rgba(0, 0, 0, 0.08), 0 2px 4px -1px rgba(0, 0, 0, 0.04)`
- **Modal Dialog:** `0 10px 15px -3px rgba(0, 0, 0, 0.1)`
- **Banned:** Colored glowing shadows, diffused multi-layer blur drops (`0 20px 25px...`).

---

## 5. Component Patterns & Rules

### 5.1 Dashboard Stat & Metric Display
- **No Rainbow Cards:** Never paint metric card surfaces in saturated red, green, orange, yellow, or navy.
- **Flexible Operational Metrics:** Do not arbitrarily force the dashboard to exactly four metrics. Preserve all useful operational indicators (e.g., Total Tracked Assets, Active Accountabilities, Maintenance Flagged, Low Stock Consumables, Pending Borrow Requests).
- **Presentation Formats:** Display metrics as either:
  1. *A Unified Metric Strip:* An integrated, border-divided horizontal summary bar within a single parent panel.
  2. *Compact Metric Cells/Cards:* Clean white cards (`#ffffff`, 8px radius, 1px border `#e2e8f0`, 16px padding).
- **Structure:**
  1. Category / Eyebrow: Slate 500, uppercase, `11px`, weight 600, tracking 0.05em.
  2. Metric Digit: Slate 900, `26px`, weight 700, monospace `tabular-nums`.
  3. Context / Delta: Slate 600, `12.5px`, weight 400 (e.g., \"3 overdue for return\").
- **No Decorative Top Stripes:** Remove legacy 3px colored accent top borders. Visual distinction is driven solely by typography and contextual status text.

### 5.2 Buttons & Action Controls
- **Primary Action (`.btn-primary-cba`):** Modern Institutional Blue (`#1d4ed8`), white text, weight 600, `6px` radius, padding `6px 14px`. Focus ring: `3px` solid `rgba(37,99,235,0.18)`.
- **Secondary Action (`.btn-secondary-cba`):** White background, 1px Slate 300 border (`#cbd5e1`), Slate 900 text. Hover: Slate 50 background (`#f8fafc`).
- **Danger Action (`.btn-danger-cba`):** Red 600 (`#dc2626`), white text. Reserved strictly for destructive operations.
- **Size Standards:**
  - Desktop: Height `36px` to `38px`.
  - Mobile: Height `44px` minimum for tap targets.
- **Clutter Gate:** Maximum of 3 visible primary/secondary actions in a page header before collapsing secondary options into an \"Actions\" dropdown.

### 5.3 Data Tables (Operational Core)
- **CRM / Database Grid Aesthetic:** Tables are the operational core. They must look like a high-density modern database tool, not a default Bootstrap striped table.
- **Header:** Height 38px, very subtle fill (`#f8fafc`), uppercase `11px` text, weight 600, Slate 600 color, hairline 1px bottom border (`#e2e8f0`). No heavy 2px dark lines.
- **Rows:** Clean white surfaces (`#ffffff`), height 40px–44px, hairline bottom divider (`#f1f5f9`). Alternating zebra striping is removed in favor of clean rows with a soft hover highlight (`#f8fafc`).
- **Active / Selected Row:** Soft blue tint (`#eff6ff`) with 1px subtle blue outline.
- **Alignment:** Property codes, serial numbers, dates, and quantities strictly right-aligned or monospace-aligned.
- **Empty States:** When 0 rows match, display a helpful institutional empty state explaining the condition and providing a clear path to populate or reset filters. Never render dead table headers.

### 5.4 Form Elements & Validation
- **Inputs & Selects:** Height `38px` (`44px` on mobile), 1px Slate 300 border (`#cbd5e1`), 6px radius, white surface, Slate 900 text.
- **Focus State:** 1px border `#2563eb`, crisp focus ring `0 0 0 3px rgba(37, 99, 235, 0.18)`.
- **Labels:** 0.85rem, Slate 700, weight 600, positioned above input. Mandatory fields marked with red asterisk `*`.
- **Validation Presentation:** Real-time and server-side errors rendered directly below the input in crimson (`#b91c1c`, 12px) with matching 1px red field border.

### 5.5 Status Badges & Asset Code Chips
- **Badges:** Subtle background tint + 1px border + dark text (defined in Section 2.4). Format: `padding: 2px 8px`, `border-radius: 4px`, `font-size: 0.72rem`, `font-weight: 600`.
- **Asset Code Chips (`.cba-code`):** Monospace font, 4px radius, 1px border (`#e2e8f0`), background `#f1f5f9`, text `#1d4ed8`.
- **Never:** Never render solid neon pill badges for routine inventory states.

### 5.6 Navigation & Layout Shell
- **Desktop Sidebar:** Width `240px`, light neutral canvas (`#f8fafc`), hairline 1px right border (`#e2e8f0`), fixed left.
  - Section headers: Slate 500, uppercase, `11px`, weight 600, tracking 0.05em.
  - Resting item: Height 34px–36px, Slate 600 text, 6px radius.
  - Active item: Soft blue tint pill (`#eff6ff`), Modern Institutional Blue text (`#1d4ed8`), weight 600. No left colored indicator lines.
  - Hover item: Slate 100 background (`#f1f5f9`), Slate 900 text.
- **Top Header Bar:** Pure white surface (`#ffffff`), height `54px`, 1px bottom border (`#e2e8f0`). Contains breadcrumb trail, user role pill, department scope indicator, and optional global search.
- **Global Search Rule (Adjusted):** Global search (`Ctrl + K` / search input) is strictly optional. Do not require or render a global search input in the header unless a genuine global search backend service is active.
- **Mobile Offcanvas:** Drawer width `260px`, light neutral styling matching desktop sidebar, trigger button minimum 44x44px.

---

## 6. Responsive Reflow & Mobile Rules

### 6.1 Breakpoints
- **Mobile:** `< 768px` (`xs` and `sm`)
- **Tablet:** `768px – 1024px` (`md`)
- **Desktop:** `> 1024px` (`lg` and `xl`)

### 6.2 Layout Behavior Rules
1. **Zero Horizontal Scroll:** The body and main containers must never produce horizontal scroll. Tables are enclosed in `.table-responsive` with clean horizontal scroll indicators or reflow into card lists on mobile screens.
2. **Touch Targets:** All interactive controls (buttons, links, select inputs, pagination items, tab triggers) must have a minimum bounding box of `44px x 44px` on mobile viewports (`< 768px`).
3. **Stat Grid Stacking:**
   - Desktop (`> 1024px`): 4-column or multi-column grid depending on metric volume.
   - Tablet (`768px – 1023px`): 2-column or 3-column grid.
   - Mobile (`< 768px`): 2-column compact grid (12px padding, reduced metric font size 1.35rem).
4. **Header Action Reflow:** Long horizontal button clusters collapse into a primary CTA + \"Actions\" dropdown under 768px.

---

## 7. Accessibility Standards (WCAG 2.1 AA)

1. **Color Independence:** Status is never communicated by color alone. Badges and indicators pair color tints with clear textual labels and descriptive icons.
2. **Focus Visibility:** High-contrast focus rings (`:focus-visible`) on all interactive controls.
3. **Screen Reader Semantics:**
   - Icon-only buttons must include `aria-label` or visually hidden `.visually-hidden` text.
   - Modals and offcanvas drawers must trap keyboard focus and restore focus on dismissal.
4. **Form Associations:** Every input is programmatically coupled with an explicit `<label for="...">`.

---

## 8. Technical Architecture & System Safeguards

### 8.1 Comprehensive RBAC & Authorization Preservation
Visual direction updates must preserve ALL existing authorization mechanisms without exception:
- `request.user.role` evaluation (Admin, Dean, Department Chair, Faculty).
- `request.user.is_admin` and `is_superuser` properties.
- Custom permission mixins (e.g., `AssignmentViewAccessMixin`, `RoleRequiredMixin`).
- Role-specific template conditionals (`{% if request.user.role == ... %}`).
- Department scoping rules (e.g., Chair scoped strictly to their department's transactions; Faculty redirected to `my_accountability`).
- Never assume standard Django model permissions (`perms.app.can_do`) are the only authorization mechanisms in templates or views.

### 8.2 HTMX Interactivity & Loading Indicator Rules
- **DOM Container IDs:** All existing container IDs (`#asset-results-container`, `#supply-results-container`, `#assignment-results-container`, etc.) and `hx-*` attributes must be preserved identically.
- **Restrained Loading Indicators (Adjusted):** The default loading pattern is the existing restrained inline indicator (`.htmx-indicator` spinners positioned inside search input groups or filter toolbars).
- **No Mandatory Skeletons:** Shimmer or skeleton screen loading is NOT a default pattern. Skeletons are permitted only where there is an explicit, proven UX requirement for large structural content shifts.

### 8.3 Alpine.js State Integrity
- Maintain existing client-side reactive state implementations: collapsible filter panels (`x-data="{ open: ... }"`), bulk QR label checkboxes (`x-model="selected"`), and inline action confirmations (`x-data="{ confirming: false }"`).
- Never remove or break `x-data`, `x-show`, `x-cloak`, `x-model`, or `@click` attributes during visual restyling.

### 8.4 Barcode & QR Scanner Safeguards
- Scanner views (`scanner.html`) using `html5-qrcode` require unobstructed camera viewports and high-contrast touch targeting reticles. Do not apply desktop panel overflows or restrictive max-heights that break camera initialization.

### 8.5 Print View Safeguards
- Print views (bulk QR label sheets, Property Acknowledgment Receipts, Property Transfer Reports, Inventory Count Sheets) are governed by strict `@media print` rules.
- Print stylesheets must enforce solid black borders (`1px solid #000000`), pure white backgrounds (`#ffffff`), and 100% opacity, completely suppressing screen-only subtle borders (`#e2e8f0`) and hiding navigation chrome (`#desktop-sidebar`, topbar, action toolbars).

---

## 9. Anti-Slop Checkpoints & Delivery Gate

Before approving any UI enhancement, the implementation must pass these six gates:
1. **No Dark Heavy Shell:** The sidebar must use the light neutral canvas (`#f8fafc`) with hairline dividers, completely retiring the dark slate `#0f172a` chrome.
2. **No AI Cliché Styles:** No purple/cyan gradients, no frosted glassmorphism, no bubble pills, no generic hero banners.
3. **No Rainbow Cards:** Metric cards and data containers must use clean white surfaces with disciplined typographic hierarchy.
4. **Institutional Tone:** Microcopy must use precise administrative language (\"Property Custodian\", \"Asset Tag\", \"Verification Queue\") rather than consumer-SaaS jargon.
5. **No Scaffolding or Developer Slop:** Never leave phase numbers (\"Phase 1 Foundation\"), raw model names (`AssetCategory`), or placeholder comments visible to the end user.
6. **Mobile Integrity:** Layout tested and verified on a 375px mobile viewport with zero horizontal overflow and 44px minimum touch targets.
