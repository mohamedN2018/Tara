# Tara brand and design system

**Connect. Share. Belong.** / **تواصل. شارك. انتمِ.**

Dark is the primary experience. Light mode uses the same identity. Arabic (RTL) is
the default language, and every screen also works in English (LTR).

## Colours

| Token | Hex | Tailwind | Use |
|---|---|---|---|
| Tara Purple | `#6A00F4` | `brand-600` | Primary actions, active navigation, links on light |
| Neon Violet | `#A855F7` | `brand-400` | Links and accents on dark, focus ring |
| Accent Pink | `#FF4ED8` | `accent-500` | Badges, unread dots, the gradient's end, "love" |
| Deep Indigo | `#0B0B1F` | `gray-950` / `ink` | Dark canvas, toasts, the auth brand panel |
| Soft Lavender | `#E8E6FF` | `lavender` | Light tints |
| White | `#FFFFFF` | `white` | Light cards, text on brand |

Proportions: about 60% dark surfaces, 25% purple, 10% white and light tints, 5% pink.

The `gray` scale is replaced by an indigo-tinted neutral scale (`tailwind.config.js`),
so surfaces, borders and muted text already carry the brand. Use these:

- Canvas: `bg-gray-100 dark:bg-gray-950`
- Card: `.card`, which is white on light and `gray-900` (`#15142F`) on dark
- Muted text: `text-gray-500 dark:text-gray-400`. Never use `gray-400` alone for text,
  because it fails contrast on white.
- Brand text: `text-brand-600 dark:text-brand-300`

**Gradient** (`bg-tara-gradient`, `.text-gradient`): purple, then violet, then pink at
135°. Use it on one main action per screen (`.btn-gradient`), the app icon, the
profile cover placeholder and the story-style avatar ring. Don't use it for
backgrounds of content areas.

## Logo

The logo follows the interface language: **Arabic gets the Arabic wordmark "تارا"; every
other language gets the English "T" mark.** The source artwork is in `frontend/Desgin/`.

- Component: `src/components/brand/TaraLogo.vue`, with the language logic in `src/lib/brand.ts`.
  - `variant`: `full` (Arabic: the wordmark; other languages: T mark plus "Tara"), `mark`, or `icon` (the app icon).
  - `tone`: `gradient` (colour artwork) or `white` (on photos or the gradient). `ink` uses the colour artwork.
  - `size`: the logo height in pixels.
- In-app artwork, exported from `frontend/Desgin/`, trimmed and resized: `src/assets/brand/tara-ar.png`, `tara-ar-white.png`, `tara-en.png` and `tara-en-white.png`.
- Icons in `public/icons/`:
  - `favicon-ar.png`, `favicon-en.png`: the tab icon, swapped by language in `theme-init.js` and `applyBrandIcons()`.
  - `icon-ar-*`, `icon-en-*`: app icons.
  - `icon-192/512.png`, `icon-maskable-512.png`: the manifest (Arabic, the default language).
  - `apple-touch-icon(-en).png`.
  - `badge-96.png`: a monochrome notification badge.
- To regenerate after the artwork changes, run `scripts/brand/export_logos.py` (usage in its header).
- Keep clear space of at least half the logo's height around it. Don't recolour or rotate it.

## Type

Manrope (Latin) with Cairo (Arabic), each falling back to the other, so mixed text
stays on-brand. Weights 400–800. Headings use `font-display font-extrabold
tracking-tight`.

## Components (`src/style.css`)

| Class | Purpose |
|---|---|
| `.card`, `.card-hover`, `.popover` | Surfaces, interactive cards, menus |
| `.btn-primary`, `.btn-gradient`, `.btn-soft`, `.btn-ghost`, `.btn-outline`, `.btn-danger` | Buttons |
| `.icon-btn` | Round header and toolbar buttons |
| `.input`, `.label` | Form fields |
| `.chip`, `.chip-active`, `.badge` | Filters, counters |
| `.nav-item`, `.nav-item-active` | Sidebar navigation |
| `.skeleton` | Shimmer loading blocks (direction-aware) |
| `.section-title`, `.text-gradient`, `.avatar-ring` | Typography and brand accents |

Radius: controls `rounded-xl`, cards `rounded-2xl`, hero panels `rounded-3xl`.
Shadows: `shadow-card`, `shadow-pop` (menus, modals), `shadow-glow` (main action).
Motion: 150–250 ms ease-out, and nothing animates under `prefers-reduced-motion`.

## Rules

- Use logical properties (`ms-`, `me-`, `start-`, `end-`), never `left`/`right`, so
  RTL and LTR both work. For direction-specific CSS, use `:dir(ltr)` / `:dir(rtl)`.
- Keep button labels and ARIA names stable: the e2e suite finds controls by role
  and name.
- Show real data only. The feed, right rail and profiles show nothing the backend
  doesn't provide (no placeholder stories, trends or suggestions).
