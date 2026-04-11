# Progress Bar Config

## Display

- **style** — `"bar"` or `"circle"`. Controls the progress indicator shape.
- **position** — `"top-left"`, `"top-right"`, `"bottom-left"`, or `"bottom-right"`.
- **theme** — `"light"`, `"dark"`, `"pink"`, `"blue"`, `"green"`, `"purple"`, `"orange"`, or `"custom"`.
- **gradient_type** — `"solid"`, `"fade"`, or `"traffic"` (red → green as you progress).
- **glass_effect** — `true`/`false`. Frosted blur overlay.
- **glass_opacity** — `0.0`–`1.0`. Opacity of the glass overlay.
- **glass_blur** — Blur radius in pixels for the glass effect.

## Bar Style

- **bar_color** — Hex color for the filled portion of the bar.
- **bar_background** — Hex color for the unfilled portion.
- **bar_thickness** — Height of the bar in pixels.

## Circle Style

- **circle_size** — Diameter of the circle in pixels.
- **circle_color** — Hex color for the filled arc.
- **circle_background** — Hex color for the unfilled arc.

## Text

- **text_color** — Hex color for all text labels.
- **text_size** — Font size in points.
- **text_brightness** — `0`–`255`. Adjusts label brightness.
- **stats_position** — `"left"` or `"right"`. Where the New/Learn/Review counts appear.

## Counts Shown

- **show_percentage** — `true`/`false`. Show completion percentage.
- **show_numbers** — `true`/`false`. Show done/total numbers.
- **show_new_count** — `true`/`false`. Show the New card count.
- **show_learning_count** — `true`/`false`. Show the Learn card count.
- **show_review_count** — `true`/`false`. Show the Review card count.

## New Card Tracking

- **include_new_cards** — `true`/`false`. Whether new cards count toward the bar.
- **new_cards_mode** — `"goal"` counts toward a daily goal you set. `"scheduler"` tracks new cards the same way as learn and review cards.
- **new_cards_goal** — Number of new cards per day (only used in `"goal"` mode).

## Visibility

- **enabled** — `true`/`false`. Show or hide the progress bar entirely.
- **display_on_home** — `true`/`false`. Show on the deck browser.
- **display_on_review** — `true`/`false`. Show during card review.
- **display_on_main** — `true`/`false`. Show on the main screen.
