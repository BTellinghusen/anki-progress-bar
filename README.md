# Anki Progress Bar

A fully customizable progress bar for Anki that tracks your daily review session in real time. Displays new, learning, and review card counts with beautiful themes, gradients, and glass effects — plus a built-in batch unsuspend system.

---

## Features

### Progress Display
- **Bar or circle style** — choose your layout
- **Real-time updates** after every card answer
- **Live counts** for New, Learn, and Review cards remaining
- **Done/total and percentage** display
- **Position** — top-left, top-right, bottom-left, or bottom-right

### Themes & Styling
- Built-in themes: Light, Dark, Pink, Blue, Green, Purple, Orange
- Custom color picker for bar fill and background
- **Traffic light gradient** — bar shifts red → orange → yellow → green as you progress
- **Frosted glass effect** — blurred, translucent overlay with adjustable opacity and blur
- Adjustable text size and brightness

### New Card Tracking (two modes)
- **Goal-based** — counts toward a manually set daily goal (e.g. 20 new cards). Resets at end of day.
- **Scheduler mode** — counts new cards the same way as learning and review cards: done from today's revlog, remaining from Anki's scheduler. No goal to maintain.

### Card Count Accuracy
- Learning cards done pulled from revlog (`type 0` learn steps + `type 2` relearn steps)
- Review cards done pulled from revlog (`type 1`)
- New cards introduced today counted from revlog (cards whose first-ever review entry was today)
- Remaining counts queried fresh from the database after every card — no stale scheduler state

### Batch Unsuspend
Create saved rules to unsuspend a set number of suspended cards each session.

**Rule builder:**
- **Multiple tags per rule** — AND logic (card must have all selected tags)
- **Multiple decks per rule** — OR logic (card can be in any selected deck)
- **Hierarchical deck browser** — top-level parents shown by default; click `▶` to drill into sub-decks; `← Back` to go up
- **Debounced search** — 300ms delay, all filtering done in-memory (no DB hit per keystroke)
- **`&` multi-term search** — type `neuro & pharm` to filter results matching both terms
- **Double-click to add** tags or decks to the rule; click selected items to remove
- **Active/inactive toggle** per rule
- **Total counter** at the bottom — sum of cards across all active rules, updates live when you toggle rules

---

## Installation

### From AnkiWeb
*(Screenshots coming — add-on page link will be here)*

### Manual
1. Download or clone this repo
2. Copy the `ProgressBar` folder into your Anki add-ons directory:
   - **macOS:** `~/Library/Application Support/Anki2/addons21/`
   - **Windows:** `%APPDATA%\Anki2\addons21\`
   - **Linux:** `~/.local/share/Anki2/addons21/`
3. Restart Anki

---

## Configuration

Open via **Tools → Progress Bar Settings** or click the progress bar itself.

| Setting | Description |
|---|---|
| Style | Bar or circle |
| Position | Corner of screen |
| Theme | Preset color scheme |
| Gradient | Solid, fade, or traffic-light |
| Glass effect | Frosted blur overlay |
| New card mode | Goal-based or scheduler |
| Daily new goal | Target if using goal mode |
| Display location | Main screen, deck overview, during review |

---

## Batch Unsuspend

Open via **Tools → Reschedule / Unsuspend Cards → Batch Unsuspend tab**.

1. Click **Add Rule**
2. Name the rule
3. Search for tags (double-click to add; use `&` for AND)
4. Browse or search for decks (double-click to add; `▶` to expand parent decks)
5. Set the number of cards to unsuspend
6. Click **Save**
7. Enable/disable rules with the checkbox — the **total counter** updates live
8. Click **Unsuspend Selected** to run all active rules

---

## Compatibility

- Anki 23.10+ (tested on 25.x)
- Python 3.10+
- macOS, Windows, Linux

---

## License

MIT
