---
name: ui-ux-product-polish
description: Improve frontend visual design, UX quality, responsive behavior, accessibility, design systems, reusable UI components, layout hierarchy, interaction states, and product polish for TravelMind. Use when changing how the UI looks, feels, moves, or is interacted with.
---

# UI/UX Product Polish

Use this skill for TravelMind frontend design, UI refactors, component styling, interaction states, responsive layout, and accessibility reviews.

## Product Direction

TravelMind should feel like a premium AI travel companion:

- Dark-first, calm, trustworthy, modern.
- AI copilot workspace + travel itinerary cards.
- Indigo / violet / cyan brand gradient.
- Soft glass panels, subtle map-route/star/grid/glow details.
- Clean typography and strong hierarchy.
- Avoid generic admin dashboards, random colors, emoji-as-icons, heavy borders, and low-contrast gray text.

## Process

1. Audit the current UI before editing:
   - Layout hierarchy, spacing rhythm, typography, color consistency.
   - Repeated components and hardcoded styles.
   - Hover, focus, active, disabled, loading, empty, and error states.
   - Mobile behavior and keyboard accessibility.
2. Reuse or extend design tokens first:
   - Colors, spacing, radius, shadow, typography, motion, z-index.
   - Do not introduce raw random hex colors in page components.
3. Refactor incrementally:
   - Preserve API, router, store, and SSE logic unless explicitly requested.
   - Extract repeated UI into reusable Vue components.
   - Prefer Vue 3 + TypeScript + CSS variables; do not add heavy UI libraries without approval.
4. Validate:
   - Run `npm run type-check`.
   - Run `npm run build` for visual-system or page-level changes.
   - Mention responsive or manual checks that still need browser verification.

## Quality Bar

A UI change is not complete unless:

- Visual hierarchy is obvious.
- Spacing and radius follow the token scale.
- Text contrast is readable.
- Interactive elements expose visible focus states.
- Buttons/inputs have meaningful disabled/loading/error states when applicable.
- Mobile layout remains usable without horizontal scroll.
- The page remains consistent with TravelMind's premium AI travel style.

## First-Choice Components

Prefer creating or reusing:

- `AppShell`
- `BaseButton`
- `BaseInput`
- `BaseTextarea`
- `GlassCard`
- `StatusBadge`
- `EvidenceBadge`
- `EmptyState`
- `LoadingState`
- `ErrorState`
- `ItineraryCard`
- `DayPlanCard`

## References

- Project design system: `docs/frontend/TravelMind前端设计系统.md`
- Global theme tokens: `frontend/DsAgentChat_web/src/styles/theme.css`
