---
name: VALZ
description: A shift is a grid of seconds, and the grid stays visible. Drawn construction grid, ink rectangles, one blue, one hot colour for broken rules.
colors:
  paper: "#ffffff"
  grid-hairline: "#e6ebf2"
  surface: "#f5f7fa"
  ink: "#111111"
  ink-soft: "#2f3742"
  muted: "#566070"
  crouwel-blue: "#0057ff"
  crouwel-blue-dark: "#0041c4"
  blue-line: "#b6cdfb"
  blue-tint: "#e6efff"
  hot: "#ff4d1a"
  hot-ink: "#a52d0b"
  hot-tint: "#ffece5"
typography:
  display:
    fontFamily: "'Chakra Petch', 'Noto Sans Thai', system-ui, sans-serif"
    fontSize: "6rem"
    fontWeight: 700
    lineHeight: 0.85
    letterSpacing: "-0.02em"
  headline:
    fontFamily: "'Chakra Petch', 'Noto Sans Thai', system-ui, sans-serif"
    fontSize: "1.75rem"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "0.02em"
  title:
    fontFamily: "'Chakra Petch', 'Noto Sans Thai', system-ui, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "0.08em"
  body:
    fontFamily: "'Noto Sans', 'Noto Sans Thai', system-ui, -apple-system, 'Hiragino Sans', 'Yu Gothic UI', Meiryo, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.5
    fontFeature: "tabular-nums"
  label:
    fontFamily: "'Chakra Petch', 'Noto Sans Thai', system-ui, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 500
    lineHeight: 1
    letterSpacing: "0.08em"
rounded:
  none: "0"
spacing:
  cell: "24px"
  xs: "0.25rem"
  sm: "0.5rem"
  md: "1rem"
  lg: "1.5rem"
  xl: "2rem"
components:
  button:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "0.4375rem 0.875rem"
    height: "2.25rem"
  button-hover:
    backgroundColor: "{colors.blue-tint}"
    textColor: "{colors.crouwel-blue-dark}"
  button-primary:
    backgroundColor: "{colors.crouwel-blue}"
    textColor: "{colors.paper}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "0.4375rem 0.875rem"
    height: "2.25rem"
  button-primary-hover:
    backgroundColor: "{colors.crouwel-blue-dark}"
  button-hot:
    backgroundColor: "{colors.hot}"
    textColor: "{colors.ink}"
  tab-active:
    backgroundColor: "{colors.crouwel-blue}"
    textColor: "{colors.paper}"
    typography: "{typography.label}"
    padding: "0 2rem"
    height: "56px"
  panel:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "1rem"
  input:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "0.4375rem 0.625rem"
    height: "2.25rem"
  chip-time:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.crouwel-blue-dark}"
    rounded: "{rounded.none}"
    padding: "0.125rem 0.5rem"
    height: "1.75rem"
  tag-priority-high:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    rounded: "{rounded.none}"
    padding: "0.1875rem 0.5rem"
  tag-severity-high:
    backgroundColor: "{colors.hot}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "0.1875rem 0.5rem"
---

# Design System: VALZ

## Overview

**Creative North Star: "The Drawn Construction Grid"**

The interface is white grid paper with a 24px hairline lattice, drawn in ink. A shift is a grid of sampled seconds, so the grid is the surface itself and every cell is a button that jumps the video to that second. Panels are hard 1px ink rectangles. Nothing is rounded, nothing casts a shadow, and the only flourish is a single diagonal stroke. The form is a Crouwel Grid Specimen: squared, chamfered display type on a visible construction grid, built for a manager reading a finished shift at a desk.

One blue (#0057ff) means selection, primary action, and the playhead. One hot orange (#ff4d1a) means a rule was broken, and nothing else. Activity classes are told apart by cell texture, never by colour alone. Density is high and ruled: readouts are rows, not cards.

**Key Characteristics:**
- Visible 24px grid under every page; boxes sit on it as drawn rectangles.
- Ink 1px borders, 0 radius, 0 shadow. Depth by outline and fill only.
- Blue for state of attention; hot orange only for broken rules.
- Chakra Petch uppercase labels with wide tracking over a neutral Noto Sans body.
- Texture (open, dot, hatch, tint, dash) carries meaning that colour alone would not.

## Colors

A near-monochrome ink-on-paper palette with one cool blue family and one hot family, both rationed.

### Primary
- **Crouwel Blue** (#0057ff): selection, primary buttons, the active slanted tab, the playhead, caret and accent-color, the focus ring, the takt diagonal on a cell, the "now" cell outline.
- **Crouwel Blue Dark** (#0041c4): hover on primary, time chips, hover text on secondary buttons, info tags.
- **Blue Line** (#b6cdfb): pressed button fill and the NVA_WAITING cell tint.
- **Blue Tint** (#e6efff): hover wash on tabs, buttons, segmented options; info notices; the Gemba Kaizen selected-row fill.

### Secondary (Hot, broken rules only)
- **Hot** (#ff4d1a): a cell's hit bar, the matrix cells where a rule is broken (full above threshold, partial tint of the same hue below it), high-severity incident tags, the top-incident plane on the Dashboard, the Review button on it.
- **Hot Ink** (#a52d0b): text and border of medium-severity incident tags. Hot Tint (#ffece5) is defined but not used by any rule seen in the build.

### Neutral
- **Paper** (#ffffff): page ground and every panel fill.
- **Grid Hairline** (#e6ebf2): the 24px lattice, row dividers, disabled borders, skeleton sweep, NO_PERSON stripes.
- **Surface** (#f5f7fa): flat panels, empty and missing-video states, disabled fills.
- **Ink** (#111111): text, every panel and control border, Gemba Kaizen high priority fill, pressed toggle fill, video letterbox.
- **Ink Soft** (#2f3742): labels, secondary text, legend text.
- **Muted** (#566070): metadata, hints, low-priority tags, zero counts.

### Named Rules
**The Broken-Rule Rule.** Hot orange appears only where a safety rule was broken. Gemba Kaizen priority, notes, warnings and every other emphasis use ink, muted or blue. Orange means a rule broke; spending it elsewhere cheapens that meaning.

**The One Blue Rule.** Blue marks where attention is (selected, current, primary, playhead). It is never a category colour; categories get texture.

## Typography

**Display Font:** Chakra Petch 500/600/700 (with Noto Sans Thai, system-ui)
**Body Font:** Noto Sans 400/600 (with Noto Sans Thai, system-ui, Hiragino Sans, Yu Gothic UI, Meiryo)
**Label/Mono Font:** Chakra Petch for labels; numerals use tabular-nums on body globally, no separate mono face.

**Character:** A squared, chamfered display face doing the work of engineering lettering, set against a plain grotesk that disappears into reading. Japanese is not self-hosted; it falls to the system Japanese faces.

### Hierarchy
- **Display** (700, 6rem, 0.85, -0.02em): the one monumental VA percentage on the Dashboard (4rem under 700px); its unit is 2.25rem in blue.
- **Headline** (700, 1.75rem, 1.1, 0.02em, uppercase): page titles.
- **Title** (600, 0.9375rem, 1.2, 0.08em, uppercase): panel headings. Larger empty-state heading 1.125rem at 0.04em; readout values 700 at 1.375rem.
- **Body** (400, 0.9375rem, 1.5): running text; prose capped near 52-62ch. Small text 0.8125rem and 0.75rem for meta and hints.
- **Label** (500, 0.8125rem or 0.75rem, 0.06-0.1em, uppercase): tabs, buttons, field labels, matrix row names. Tags are 600 at 0.6875rem; cell tick numbers 600 at 0.625rem.

The scale in use is 0.75 / 0.8125 / 0.9375 / 1.125 / 1.375 / 1.75rem (xs to 2xl), then the display jump.

### Named Rules
**The Uppercase Ruler Rule.** Every label, tab, button and panel heading is uppercase Chakra Petch with positive tracking. Body text is never uppercase.

## Layout

The page is a grid on grid paper. The body background is a 24px (--cell) lattice of 1px #e6ebf2 hairlines, offset -1px so lines sit under box borders. The page container is max 1440px, padded 1.5rem (1rem under 900px), with 1.5rem gaps between boxes. Spacing steps in use: 0.25, 0.5, 0.75, 1, 1.5, 2rem.

Shell: a sticky 56px top bar, ruled in blue, holding brand, four cell-tabs (Video, Safety Agent, Dashboard, Gemba Kaizen) and an end cluster (video toggle, run-status chip, report-language select).

Dashboard first screen is two columns (1.05fr / 1fr): the gridded VA figure and ruled readout left; video and the top-incident plane right; the shift grid full width beneath. The shift grid is one square cell per second, one row per minute, 60 columns by default (--cols), each cell a 1px ink-bordered square. Safety is a 26rem rule column beside the findings; Gemba Kaizen is a content column plus a 24rem detail column; Video is content plus a 22rem side.

Responsive: pages are container-query driven (the page is an inline-size container), so they answer to the room left after the video column. Dashboard, Gemba Kaizen and Safety collapse to one column at container width 1100px, Video at 1000px. Viewport rules: under 900px the top bar wraps to brand, tabs, and end cluster rows (48px rows, tabs flex evenly, active tab loses its slant); under 700px the rule matrix lead column shrinks from 10rem to 6rem and tail from 3rem to 2.25rem, and the Dashboard figure drops to 4rem.

Video dock: when a clip is loaded and the page is not Video or Dashboard, a 24rem dock opens. At 1200px and wider it is a fixed right column and the content gets 26rem of right padding. Under 1200px it is a bottom sheet (min(24rem, viewport minus 2rem)) and the content gets 19rem of bottom padding. Under 700px it is a full-width sheet with a top border only and 17rem of bottom padding. The dock never covers content.

## Elevation & Depth

Flat. There are no shadows and no blur: depth is stacking by outline. Panels are 1px ink rectangles; "flat" panels drop to a hairline border on Surface; the sticky bar sits at z 30 and the dock at z 40, separated by rules only. Hover on a cell is a 2px blue inset outline, never a lift. A hot hit bar on a cell is a 5px strip at its foot.

### Named Rules
**The No-Shadow Rule.** Separation is a 1px line or a change of fill. No box-shadow, no radius, no gradient fills except the structural ones below (cell textures, the takt diagonal, the loading sweep).

## Shapes

Hard rectangles. Every border radius is 0, including inputs, chips, tags, buttons and the segmented control. Borders are 1px solid: ink for boxes and controls, hairline for dividers and disabled states, blue for the top bar rules and chips, dashed ink for empty states and the UNCERTAIN cell. The slanted active tab is the one angled shape; the diagonal slash is the one ornament.

- **Slanted active tab:** clip-path polygon with 14px chamfers (parallelogram), blue fill, white label, -7px side margin and 2rem inline padding so it overlaps its neighbours.
- **Diagonal slash:** a 14px square-capped stroke from lower-left to upper-right, currentColor, used after the brand name (the full stop in the brand is blue) and in headers. One per surface region, not a pattern fill.

## Components

### Buttons
- **Shape:** square, 1px ink border, min height 2.25rem (small 1.875rem), padding 0.4375rem 0.875rem; Chakra Petch 500 uppercase, 0.08em.
- **Default:** paper fill, ink text. **Hover:** blue-tint fill, blue border, dark-blue text. **Active:** blue-line fill. **Pressed toggle:** ink fill, white text.
- **Primary:** blue fill, white text; hover goes to dark blue.
- **Hot:** hot fill, ink text, ink border; only for acting on a broken rule (e.g. Review all).
- **Disabled:** surface fill, hairline border, muted text, not-allowed cursor.
- Transitions are 0.15s ease-out on colour only.

### Navigation
Cell-tabs: uppercase labels, 1.5rem padding, hairline right dividers, blue-tint hover. The current tab is a slanted blue plane with white text. Mobile: tabs fill the row evenly at 0.6875rem and the active tab becomes a plain blue rectangle.

### Inputs / Fields
Square, 1px ink border, paper fill, 2.25rem min height. Focus: 2px blue outline at offset 0 plus a blue border. Disabled: surface fill, hairline border, muted text. Labels are small uppercase Chakra Petch above the field. Segmented control: joined ink-ruled buttons, selected = blue fill, white text.

### Panels
Paper fill, 1px ink border, a header row ruled with an ink bottom border (uppercase title left, muted meta right), body padding 1rem. Flat variant: surface fill with hairline border. Empty state: surface fill, dashed ink border. Notices: 1px ink border; info variant blue-tint with blue border.

### Tags and chips
Tags are 1px currentColor rectangles, 0.6875rem uppercase. Incident severity: high is hot fill with ink text, medium is hot-ink text, low is muted. Gemba Kaizen priority: high is ink fill with white text, medium is ink text, low and notes are muted. Time chips: paper fill, blue border, dark-blue tabular text; a clickable chip inverts to blue fill with white text on hover and jumps the video.

### Shift Cell (signature)
One sampled second: an aspect-ratio 1 square with right and bottom ink borders inside a grid ruled top and left. Activity is shown by texture:
- **VA:** open paper.
- **NNVA:** ink dot on paper.
- **NVA_MOTION:** single 135-degree blue hatch, 1px lines every 5px.
- **NVA_TRANSPORT:** cross-hatch (45 and 135 degrees, blue).
- **NVA_WAITING:** solid blue-line tint.
- **NVA_SEARCH:** small blue dot lattice, 6px pitch.
- **NO_PERSON:** vertical hairline stripes on surface.
- **UNCERTAIN:** open paper with a dashed ink inset outline.
Overlays: a hot 5px hit bar at the cell foot for a broken rule; a blue diagonal across the cell marks takt; a 2px blue inset outline marks the current second (and hover); minute ticks print the number in the corner.

### Rule Matrix
Rows of rule name (10rem lead), a track of per-second slices, and a count tail (3rem), ruled in ink. Broken slices are solid hot at or above the threshold and a hot tint scaled by confidence below it. A 2px blue playhead runs across all rows; the track takes a 2px blue inset focus ring. Rules without data show a surface hatch with muted text.

### Video player and dock
16:9 ink letterbox. Missing video: surface fill, dashed ink border. The dock is a paper box with an ink border and a ruled header (uppercase file name, dark-blue time).

### Loading
A hairline-and-surface skeleton sweep (1.2s linear) and a blue slide bar on the video progress. Both stop under reduced motion, where all transitions are also reduced to near-zero.

## Do's and Don'ts

### Do:
- **Do** draw every box as a 1px ink rectangle with 0 radius on paper or surface fill.
- **Do** keep the 24px hairline lattice visible behind the page.
- **Do** reserve hot (#ff4d1a) for broken rules; show Gemba Kaizen priority with ink fill (high), ink text (medium), muted (low).
- **Do** distinguish activity classes by texture first; use blue only as a hatch or tint inside a texture.
- **Do** make every number, cell and finding a control that jumps the video, with a time chip.
- **Do** use the blue 2px outline (offset 2px) as the focus ring and keep it visible; in-field focus uses offset 0.
- **Do** disable motion under prefers-reduced-motion.
- **Do** answer to container width, not just viewport width, because the video column consumes space.

### Don't:
- **Don't** add shadows, blur, rounded corners or gradient fills to boxes.
- **Don't** use blue as a category colour or hot as a decorative or warning colour.
- **Don't** return to card-and-sparkline dashboards: readouts are ruled rows.
- **Don't** let the video dock cover content; give the content room instead.
- **Don't** use more than one slash flourish per region.
- **Don't** express an activity class by colour alone.
