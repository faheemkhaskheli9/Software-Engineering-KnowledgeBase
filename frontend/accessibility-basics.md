---
title: Accessibility basics
category: frontend
tags: [accessibility, a11y, wcag, wcag-2.2, aria, semantic-html, keyboard, focus, color-contrast, screen-reader, axe, forms]
use_cases:
  - "make our web app meet WCAG 2.2 AA for a customer or legal requirement"
  - "check whether our brand colours have enough text contrast"
  - "make a custom dropdown or modal usable with keyboard and screen reader"
  - "add automated accessibility checks to CI and plan manual testing"
  - "make form validation errors understandable to all users"
status: draft
last_verified: 2026-10-11
sources:
  - https://www.w3.org/TR/WCAG22/
  - https://www.w3.org/WAI/standards-guidelines/wcag/new-in-22/
  - https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html
  - https://www.w3.org/TR/using-aria/
  - https://www.w3.org/TR/accname-1.2/
  - https://www.w3.org/WAI/ARIA/apg/
  - https://www.w3.org/WAI/test-evaluate/
  - https://developer.mozilla.org/en-US/docs/Learn_web_development/Core/Accessibility/HTML
  - https://github.com/dequelabs/axe-core
---

# Accessibility basics

## Summary
Accessibility (a11y) means people with visual, motor, hearing or cognitive
disabilities can perceive, operate and understand your interface, often
through assistive technology such as screen readers, switch devices or
magnification. The Web Content Accessibility Guidelines (WCAG) 2.2 are the
reference standard, organised under four principles and testable success
criteria at levels A, AA and AAA; AA is the level most policies and contracts
ask for. In practice most of the work is using semantic HTML, giving every
control an accessible name, making everything keyboard operable with visible
focus, meeting contrast ratios, and testing with tools plus humans.

## Key concepts
- **POUR:** WCAG's four principles: perceivable, operable, understandable, robust. Each holds guidelines, and each guideline holds testable success criteria (SC).
- **Conformance levels:** A (lowest), AA, AAA (highest). AA includes all A criteria. Examples: SC 2.1.1 Keyboard (A), SC 1.1.1 Non-text Content (A), SC 4.1.2 Name, Role, Value (A), SC 1.4.3 Contrast Minimum (AA), SC 2.4.7 Focus Visible (AA).
- **New in WCAG 2.2:** nine criteria, including at AA 2.4.11 Focus Not Obscured (Minimum), 2.5.7 Dragging Movements, 2.5.8 Target Size (Minimum: at least 24 by 24 CSS pixels, with exceptions) and 3.3.8 Accessible Authentication (Minimum). SC 4.1.1 Parsing is obsolete and removed.
- **Semantic HTML first:** native `<button>`, `<a href>`, `<label>`, `<nav>`, `<main>`, headings and lists carry role, name, state and keyboard behaviour for free. A `<div onclick>` has none of it.
- **Accessible name:** the text assistive technology announces for an element, computed per the W3C Accessible Name spec from content, `<label>`, `alt`, `aria-labelledby` or `aria-label`. Every interactive element and informative image needs one; decorative images get `alt=""`.
- **Rules of ARIA use (W3C):** 1) if a native HTML element or attribute with the needed semantics and behaviour exists, use it instead of ARIA; 2) do not change native semantics unless you have to; 3) all interactive ARIA controls must be keyboard usable; 4) never put `role="presentation"` or `aria-hidden="true"` on a focusable element. ARIA changes what is announced, not how anything behaves.
- **Keyboard and focus:** everything works with Tab, Shift+Tab, Enter, Space and arrow keys where the pattern expects them (SC 2.1.1); no keyboard traps (SC 2.1.2); focus order preserves meaning (SC 2.4.3); the focus indicator is visible (SC 2.4.7). Dialogs move focus in, keep it there while open, and return it to the trigger on close. The WAI-ARIA Authoring Practices Guide (APG) gives the expected keyboard model for each widget pattern.
- **Contrast ratio:** `(L1 + 0.05) / (L2 + 0.05)` where L1 and L2 are the relative luminances of the lighter and darker colour, ranging from 1:1 to 21:1. SC 1.4.3 (AA) requires at least 4.5:1 for normal text and 3:1 for large text (at least 18 point, or 14 point bold); SC 1.4.11 (AA) requires 3:1 for user interface components and meaningful graphics. Values are not rounded: 4.499:1 fails 4.5:1.
- **Forms and errors:** every input has a visible label or instructions (SC 3.3.2, A); detected errors are identified and described in text (SC 3.3.1, A), not only by colour.

## When to use / scenarios
- Always, for anything users touch; retrofitting is far more expensive than building in. Public sector, education, banking and enterprise buyers frequently make WCAG AA a contractual or legal requirement.
- Building a custom widget (combobox, tabs, menu, modal): first check whether a native element works (`<select>`, `<details>`, `<dialog>`); if not, follow the APG pattern for its roles, states and keyboard model.
- Choosing a design system's colours: compute contrast for every text/background pair before shipping tokens.
- Not a substitute: automated checks alone. W3C states that no tool alone can determine whether a site meets accessibility standards; knowledgeable human evaluation is required.

## How it works / example

Native first, ARIA only to fill gaps:

```html
<!-- bad: no role, no name semantics, not focusable, no Enter/Space -->
<div class="btn" onclick="save()">Save</div>

<!-- good: role, focus and keyboard behaviour come with the element -->
<button type="button" onclick="save()">Save</button>

<!-- icon-only control: give it an accessible name -->
<button type="button" aria-label="Close dialog"><svg aria-hidden="true">...</svg></button>

<!-- labelled input with an error tied to it -->
<label for="email">Email</label>
<input id="email" type="email" aria-invalid="true" aria-describedby="email-err">
<p id="email-err">Enter an email address like name@example.com.</p>
```

WCAG relative luminance and contrast ratio, checked against known values
(formula from the WCAG 2.2 glossary, which uses the 0.04045 sRGB threshold):

```python
def channel(c8: int) -> float:
    c = c8 / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

def luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)

def contrast(fg: str, bg: str) -> float:
    hi, lo = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)

def passes_aa(fg: str, bg: str, large_text: bool = False) -> bool:
    return contrast(fg, bg) >= (3.0 if large_text else 4.5)   # no rounding

assert luminance("#000000") == 0.0 and luminance("#ffffff") == 1.0
assert contrast("#000000", "#ffffff") == 21.0           # maximum
assert contrast("#ffffff", "#ffffff") == 1.0            # minimum
assert contrast("#123456", "#abcdef") == contrast("#abcdef", "#123456")  # symmetric
assert passes_aa("#767676", "#ffffff")                  # about 4.54:1
assert not passes_aa("#777777", "#ffffff")              # about 4.48:1, fails body text
assert passes_aa("#777777", "#ffffff", large_text=True) # fine for large text
assert not passes_aa("#959595", "#ffffff", large_text=True)  # just under 3:1
print(round(contrast("#767676", "#ffffff"), 2))         # 4.54
```

A practical testing loop:

```
1. Automated: axe-core (browser extension, Playwright/Cypress integration) in CI on key pages.
2. Keyboard only: unplug the mouse; Tab through every flow; check focus is visible,
   ordered, never trapped, and returns after dialogs close.
3. Screen reader: NVDA or JAWS (Windows), VoiceOver (macOS/iOS), TalkBack (Android);
   check names, roles, states, headings and live updates.
4. Zoom and reflow: 200% zoom and a narrow viewport; nothing clipped or overlapping.
5. Users: include people with disabilities in usability testing where possible.
```

## Trade-offs
- **Native elements vs custom styling:** native controls are accessible by default but harder to style fully; custom widgets look exactly as designed but you must rebuild roles, states, focus and keyboard support, and keep them working.
- **AA vs AAA:** AA is the common target; AAA is not achievable for all content (W3C does not recommend requiring it as a blanket policy), so apply AAA criteria selectively where they matter.
- **Automated vs manual testing:** automated tools are cheap and run on every commit but only catch what can be checked mechanically (missing alt, contrast, invalid ARIA); keyboard and screen-reader testing is slower but catches broken flows.
- **Brand colours vs contrast:** a light brand colour may fail on white; use it for large text, borders or backgrounds and a darker shade for body text.
- **Hiding content:** `display: none` hides from everyone; a visually-hidden CSS class keeps text for screen readers; `aria-hidden` hides from assistive technology only. Pick by audience.

## Gotchas
- `aria-label` on a non-interactive `<div>` or `<span>` is often ignored; names belong on controls, landmarks and images.
- A placeholder is not a label: it disappears on input and often fails contrast.
- `outline: none` without a replacement focus style fails SC 2.4.7 and leaves keyboard users lost.
- Positive `tabindex` values create a focus order that diverges from the visual order; use `0` or `-1` only.
- Colour alone to signal errors or status fails users who cannot distinguish it; add text or icons.
- Opening a modal without moving focus, or closing it without returning focus, strands keyboard and screen-reader users.
- Sticky headers and cookie banners can cover the focused element (SC 2.4.11 in WCAG 2.2).
- Contrast tools that round to one decimal can report 4.5:1 for a pair that is actually 4.48:1.
- Dynamic updates (toasts, validation, search results) are silent to screen readers unless announced through a live region or focus move.
- A clean axe report does not mean accessible; it means no machine-detectable failures were found.

## Related
- [[browser-rendering-and-core-web-vitals]] - stable layout and responsive input help users of assistive technology too.
- [[internationalization-and-localization]] - the `lang` attribute, text direction and expansion also affect screen readers and layout.
- [[testing-strategy-and-pyramid]] - where automated a11y checks sit among other tests.
- [[authentication-and-sessions]] - WCAG 2.2 SC 3.3.8 on cognitive-function tests in login flows.
- [[snapshot-and-golden-testing]] - accessibility-tree snapshots as a regression check.

## References
- W3C, Web Content Accessibility Guidelines (WCAG) 2.2, including the glossary definitions of relative luminance and contrast ratio: https://www.w3.org/TR/WCAG22/
- W3C WAI, What's new in WCAG 2.2: https://www.w3.org/WAI/standards-guidelines/wcag/new-in-22/
- W3C WAI, Understanding SC 1.4.3 Contrast (Minimum): https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html
- W3C, Using ARIA (rules of ARIA use): https://www.w3.org/TR/using-aria/
- W3C, Accessible Name and Description Computation 1.2: https://www.w3.org/TR/accname-1.2/
- W3C WAI, ARIA Authoring Practices Guide: https://www.w3.org/WAI/ARIA/apg/
- W3C WAI, Evaluating Web Accessibility Overview: https://www.w3.org/WAI/test-evaluate/
- MDN, HTML: a good basis for accessibility: https://developer.mozilla.org/en-US/docs/Learn_web_development/Core/Accessibility/HTML
- Deque, axe-core: https://github.com/dequelabs/axe-core
