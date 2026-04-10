"""
Custom Progress Bar - Anki Add-on
Shows your daily review progress with customizable bar or circular display
"""

from aqt import mw, gui_hooks
from aqt.qt import (QAction, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                    QSpinBox, QPushButton, QComboBox, QCheckBox, QListWidget,
                    QListWidgetItem, QColorDialog, QGroupBox, QAbstractItemView,
                    QTreeWidget, QTreeWidgetItem, Qt, QTabWidget, QWidget,
                    QScrollArea, QLineEdit, QCompleter, QTextEdit, QTimer)
from aqt.reviewer import Reviewer
from aqt.utils import showInfo, tooltip, askUser, getOnlyText, showWarning
from anki.utils import pointVersion
from anki.cards import Card
import json
import datetime

# Version check for Anki API compatibility
IS_AT_LEAST_VERSION_23 = pointVersion() >= 231000

# Card states
DUE = 2
SUSPENDED = -1

# Default configuration
DEFAULT_CONFIG = {
    "style": "bar",  # "bar" or "circle"
    "position": "top-left",
    "bar_color": "#FF69B4",
    "bar_background": "#E0E0E0",
    "bar_thickness": 8,
    "circle_size": 80,
    "circle_color": "#FF69B4",
    "circle_background": "#E0E0E0",
    "text_color": "#000000",
    "enabled": True,
    "selected_decks": [],
    "include_new_cards": True,
    "new_cards_mode": "goal",
    "new_cards_goal": 20,
    "show_percentage": True,
    "show_numbers": True,
    "show_new_count": True,
    "show_learning_count": True,
    "show_review_count": True,
    "text_size": 12,
    "stats_position": "left",
    "display_on_home": True,
    "display_on_review": True,
    "display_on_main": True,
    "gradient_type": "solid",  # solid, fade, or traffic
    "theme": "light",  # light, dark, nord, dracula, solarized_dark, monokai, custom
    "glass_effect": False,
    "glass_opacity": 0.5,  # Lower for better translucency to see background
    "glass_blur": 15,
    "text_brightness": 255,  # 0-255, how bright/white the text appears (255 = full white)
}

def get_config():
    """Load configuration from Anki's config system"""
    config = mw.addonManager.getConfig(__name__)
    if config is None:
        config = DEFAULT_CONFIG.copy()
        mw.addonManager.writeConfig(__name__, config)
    for key, value in DEFAULT_CONFIG.items():
        if key not in config:
            config[key] = value
    return config

def save_config(config):
    """Save configuration to Anki's config system"""
    mw.addonManager.writeConfig(__name__, config)

def get_theme_colors(theme):
    """Get color preset for a theme"""
    themes = {
        "light": {
            "text_color": "#000000",
            "bar_background": "#E0E0E0",
            "circle_background": "#E0E0E0"
        },
        "dark": {
            "text_color": "#FFFFFF",
            "bar_background": "#2D2D2D",
            "circle_background": "#2D2D2D"
        },
        "nord": {
            "text_color": "#D8DEE9",
            "bar_background": "#3B4252",
            "circle_background": "#3B4252",
            "bar_color": "#88C0D0",
            "circle_color": "#88C0D0"
        },
        "dracula": {
            "text_color": "#F8F8F2",
            "bar_background": "#282A36",
            "circle_background": "#282A36",
            "bar_color": "#BD93F9",
            "circle_color": "#BD93F9"
        },
        "solarized_dark": {
            "text_color": "#93A1A1",
            "bar_background": "#002B36",
            "circle_background": "#002B36",
            "bar_color": "#268BD2",
            "circle_color": "#268BD2"
        },
        "monokai": {
            "text_color": "#F8F8F2",
            "bar_background": "#272822",
            "circle_background": "#272822",
            "bar_color": "#66D9EF",
            "circle_color": "#66D9EF"
        }
    }
    return themes.get(theme, themes["light"])

def get_progress_data():
    """Calculate current progress based on Anki's collection stats"""
    config = get_config()
    day_start = mw.col.sched.dayCutoff - 86400

    # Done today from revlog: type 0+2 = learn/relearn steps, type 1 = reviews
    done_result = mw.col.db.first(f"""
        SELECT
            COUNT(*) as total_reviews,
            SUM(CASE WHEN type IN (0, 2) THEN 1 ELSE 0 END) as learning_reviews,
            SUM(CASE WHEN type = 1 THEN 1 ELSE 0 END) as review_reviews
        FROM revlog
        WHERE id/1000 >= {day_start}
    """)
    learning_done = done_result[1] or 0
    review_done = done_result[2] or 0

    # New cards introduced today = cards whose first-ever revlog entry is today
    new_today_result = mw.col.db.first(f"""
        SELECT COUNT(*) FROM (
            SELECT cid FROM revlog
            GROUP BY cid
            HAVING MIN(id)/1000 >= {day_start}
        )
    """)
    new_cards_today = new_today_result[0] or 0

    # Remaining from SQL (fresh DB query, not stale scheduler state)
    try:
        today = mw.col.sched.today
        dayCutoff = mw.col.sched.dayCutoff
        remaining_result = mw.col.db.first(f"""
            SELECT
                COUNT(DISTINCT CASE WHEN (queue = 1 AND due < {dayCutoff}) OR (queue = 3 AND due <= {today}) THEN id END),
                COUNT(DISTINCT CASE WHEN queue = 2 AND due <= {today} THEN id END)
            FROM cards WHERE queue >= 0
        """)
        learning_remaining = remaining_result[0] or 0
        review_remaining = remaining_result[1] or 0
    except Exception:
        learning_remaining = 0
        review_remaining = 0

    # New cards: goal-based or scheduler-based
    if config.get("include_new_cards", True):
        new_cards_mode = config.get("new_cards_mode", "goal")
        if new_cards_mode == "scheduler":
            # Count the same way as learning/review: done from revlog, remaining from deck tree
            new_done = new_cards_today
            try:
                # deck_due_tree() returns the full collection tree — each top-level child's
                # new_count already rolls up its sub-decks, so summing them gives the
                # collection-wide total without being scoped to the currently selected deck
                tree = mw.col.sched.deck_due_tree()
                new_remaining = sum(child.new_count for child in tree.children)
            except Exception:
                new_remaining = 0
        else:
            # Goal-based: count toward a fixed daily target
            new_cards_goal = config.get("new_cards_goal", 20)
            new_done = min(new_cards_today, new_cards_goal)
            new_remaining = max(0, new_cards_goal - new_cards_today)
    else:
        new_done = 0
        new_remaining = 0

    total_done = new_done + review_done + learning_done
    total_remaining = new_remaining + learning_remaining + review_remaining

    return {
        "done": total_done,
        "remaining": total_remaining,
        "new_done": new_done,
        "new_remaining": new_remaining,
        "learning_done": learning_done,
        "learning_remaining": learning_remaining,
        "review_done": review_done,
        "review_remaining": review_remaining
    }

def get_gradient_color(percentage, gradient_type, base_color):
    """Calculate gradient color based on percentage and type"""
    if gradient_type == "fade":
        # Light to dark fade
        return None, f"linear-gradient(to right, {base_color}80, {base_color})"
    
    elif gradient_type == "traffic":
        # Traffic light: red -> orange -> yellow -> green based on percentage
        stops = []
        
        if percentage < 25:
            # Red to orange
            ratio = percentage / 25
            r = 220
            g = int(50 + (140 - 50) * ratio)
            b = 50
            stops.append(f"rgb({r}, {g}, {b}) 0%")
            stops.append(f"rgb({r}, {g}, {b}) 100%")
        elif percentage < 50:
            # Red to orange to yellow
            ratio = (percentage - 25) / 25
            stops.append("rgb(220, 50, 50) 0%")
            stops.append(f"rgb(255, {int(140 + (200 - 140) * ratio)}, 50) 100%")
        elif percentage < 75:
            # Red to yellow to light green
            ratio = (percentage - 50) / 25
            stops.append("rgb(220, 50, 50) 0%")
            stops.append("rgb(255, 165, 50) 33%")
            stops.append(f"rgb({int(255 - (135 * ratio))}, 200, {int(50 + (50 * ratio))}) 100%")
        else:
            # Full spectrum
            ratio = (percentage - 75) / 25
            stops.append("rgb(220, 50, 50) 0%")
            stops.append("rgb(255, 165, 50) 25%")
            stops.append("rgb(255, 200, 50) 50%")
            stops.append("rgb(120, 200, 100) 75%")
            stops.append(f"rgb({int(120 - (70 * ratio))}, 200, {int(100 - (50 * ratio))}) 100%")
        
        gradient = f"linear-gradient(to right, {', '.join(stops)})"
        return None, gradient
    
    return base_color, None

def get_progress_html():
    """Generate HTML for the progress bar"""
    config = get_config()
    
    if not config.get("enabled", True):
        return ""
    
    data = get_progress_data()
    done = data["done"]
    remaining = data["remaining"]
    total = done + remaining
    
    if total == 0:
        percentage = 100
    else:
        percentage = int((done / total) * 100)
    
    style = config.get("style", "bar")
    
    if style == "bar":
        return get_bar_html(percentage, data, config)
    else:
        return get_circle_html(percentage, data, config)

def get_bar_html(percentage, data, config):
    """Generate HTML for bar-style progress"""
    position = config.get("position", "top-left")
    base_bar_color = config.get("bar_color", "#FF69B4")
    bg_color = config.get("bar_background", "#E0E0E0")
    text_color = config.get("text_color", "#000000")
    text_size = config.get("text_size", 12)
    gradient_type = config.get("gradient_type", "solid")
    
    # Apply theme
    theme = config.get("theme", "light")
    if theme != "custom":
        theme_colors = get_theme_colors(theme)
        text_color = theme_colors.get("text_color", text_color)
        bg_color = theme_colors.get("bar_background", bg_color)
        if "bar_color" in theme_colors:
            base_bar_color = theme_colors["bar_color"]
    
    # Glass effect settings
    glass_effect = config.get("glass_effect", False)
    glass_opacity = config.get("glass_opacity", 0.5)
    glass_blur = config.get("glass_blur", 15)
    
    # Text brightness override (for fine-tuning text visibility)
    text_brightness = config.get("text_brightness", 255)
    if text_brightness != 255:
        text_color = f"rgb({text_brightness}, {text_brightness}, {text_brightness})"
    
    # Calculate gradient
    solid_color, gradient_css = get_gradient_color(percentage, gradient_type, base_bar_color)
    
    if gradient_css:
        bar_fill_style = f"background: {gradient_css};"
    else:
        bar_fill_style = f"background: {solid_color if solid_color else base_bar_color};"
    
    show_percentage = config.get("show_percentage", True)
    show_numbers = config.get("show_numbers", True)
    show_new = config.get("show_new_count", True)
    show_learning = config.get("show_learning_count", True)
    show_review = config.get("show_review_count", True)
    
    done = data["done"]
    total = done + data["remaining"]
    
    position_styles = {
        "top-left": "top: 10px; left: 10px;",
        "top-right": "top: 10px; right: 10px;",
        "bottom-left": "bottom: 10px; left: 10px;",
        "bottom-right": "bottom: 10px; right: 10px;",
    }
    
    stats_parts = []
    if show_percentage:
        stats_parts.append(f"{percentage}%")
    if show_numbers:
        stats_parts.append(f"{done}/{total}")
    
    breakdown_parts = []
    if show_new:
        breakdown_parts.append(f"New: {data['new_remaining']}")
    if show_learning:
        breakdown_parts.append(f"Learn: {data['learning_remaining']}")
    if show_review:
        breakdown_parts.append(f"Review: {data['review_remaining']}")
    
    stats_text = " | ".join(stats_parts) if stats_parts else ""
    breakdown_text = " | ".join(breakdown_parts) if breakdown_parts else ""
    
    # Glass effect styling
    if glass_effect:
        # TRUE frosted glass: NO background color, just blur and a subtle white tint
        # This lets your background image show through completely
        glass_style = f"""background: rgba(255, 255, 255, {glass_opacity * 0.15});
            backdrop-filter: blur({glass_blur}px) saturate(180%) brightness(1.1);
            -webkit-backdrop-filter: blur({glass_blur}px) saturate(180%) brightness(1.1);
            border: 1px solid rgba(255, 255, 255, 0.2);
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);"""
    else:
        # Solid background when glass is off
        glass_style = f"background: {bg_color}; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);"
    
    return f"""
    <div id="progress-stats-box" style="
        position: fixed;
        {position_styles.get(position, position_styles['top-left'])}
        {glass_style}
        color: {text_color};
        font-size: {text_size}px;
        font-weight: bold;
        padding: 6px 10px;
        border-radius: 8px;
        z-index: 10000;
        pointer-events: auto;
        line-height: 1.3;
        max-width: 250px;
        overflow: hidden;
    ">
        <div style="
            position: absolute;
            left: 0;
            top: 0;
            bottom: 0;
            width: {percentage}%;
            {bar_fill_style}
            z-index: 0;
            transition: width 0.3s ease-out, background 0.3s ease-out;
            pointer-events: none;
        "></div>
        <div style="position: relative; z-index: 1; pointer-events: none;">
            <div style="white-space: nowrap;">{stats_text}</div>
            {f'<div style="font-size: {text_size - 2}px; opacity: 0.9; margin-top: 2px; white-space: nowrap;">{breakdown_text}</div>' if breakdown_text else ''}
        </div>
        <!-- Reschedule Icon -->
        <div id="progress-reschedule-btn" onclick="pycmd('progressbar:reschedule')" style="
            position: absolute;
            top: 4px;
            right: 4px;
            width: 12px;
            height: 12px;
            cursor: pointer;
            opacity: 0.6;
            transition: opacity 0.2s;
            z-index: 2;
            pointer-events: auto;
        " onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0.6'">
            <svg width="12" height="12" viewBox="0 0 16 16" fill="{text_color}">
                <!-- Gear/Settings Icon -->
                <path d="M8 4.754a3.246 3.246 0 1 0 0 6.492 3.246 3.246 0 0 0 0-6.492zM5.754 8a2.246 2.246 0 1 1 4.492 0 2.246 2.246 0 0 1-4.492 0z"/>
                <path d="M9.796 1.343c-.527-1.79-3.065-1.79-3.592 0l-.094.319a.873.873 0 0 1-1.255.52l-.292-.16c-1.64-.892-3.433.902-2.54 2.541l.159.292a.873.873 0 0 1-.52 1.255l-.319.094c-1.79.527-1.79 3.065 0 3.592l.319.094a.873.873 0 0 1 .52 1.255l-.16.292c-.892 1.64.901 3.434 2.541 2.54l.292-.159a.873.873 0 0 1 1.255.52l.094.319c.527 1.79 3.065 1.79 3.592 0l.094-.319a.873.873 0 0 1 1.255-.52l.292.16c1.64.893 3.434-.902 2.54-2.541l-.159-.292a.873.873 0 0 1 .52-1.255l.319-.094c1.79-.527 1.79-3.065 0-3.592l-.319-.094a.873.873 0 0 1-.52-1.255l.16-.292c.893-1.64-.902-3.433-2.541-2.54l-.292.159a.873.873 0 0 1-1.255-.52l-.094-.319z"/>
            </svg>
        </div>
    </div>
    """

def get_circle_html(percentage, data, config):
    """Generate HTML for circular progress"""
    position = config.get("position", "top-right")
    size = config.get("circle_size", 80)
    base_circle_color = config.get("circle_color", "#FF69B4")
    bg_color = config.get("circle_background", "#E0E0E0")
    text_color = config.get("text_color", "#000000")
    text_size = config.get("text_size", 12)
    gradient_type = config.get("gradient_type", "solid")
    
    # Apply theme
    theme = config.get("theme", "light")
    if theme != "custom":
        theme_colors = get_theme_colors(theme)
        text_color = theme_colors.get("text_color", text_color)
        bg_color = theme_colors.get("circle_background", bg_color)
        if "circle_color" in theme_colors:
            base_circle_color = theme_colors["circle_color"]
    
    # Glass effect settings
    glass_effect = config.get("glass_effect", False)
    glass_opacity = config.get("glass_opacity", 0.5)
    glass_blur = config.get("glass_blur", 15)
    
    # Text brightness override
    text_brightness = config.get("text_brightness", 255)
    if text_brightness != 255:
        text_color = f"rgb({text_brightness}, {text_brightness}, {text_brightness})"
    
    # Calculate gradient
    solid_color, gradient_css = get_gradient_color(percentage, gradient_type, base_circle_color)
    
    show_percentage = config.get("show_percentage", True)
    show_numbers = config.get("show_numbers", True)
    show_new = config.get("show_new_count", True)
    show_learning = config.get("show_learning_count", True)
    show_review = config.get("show_review_count", True)
    
    done = data["done"]
    total = done + data["remaining"]
    
    position_styles = {
        "top-left": f"top: 15px; left: 15px;",
        "top-right": f"top: 15px; right: 15px;",
        "bottom-left": f"bottom: 15px; left: 15px;",
        "bottom-right": f"bottom: 15px; right: 15px;"
    }
    
    # Calculate circle parameters
    radius = size / 2
    circumference = 2 * 3.14159 * (radius - 5)
    stroke_dashoffset = circumference - (percentage / 100) * circumference
    
    # Text color for traffic gradient
    inner_text_color = text_color
    if gradient_type == "traffic":
        if percentage < 25:
            inner_text_color = "rgb(220, 50, 50)"
        elif percentage < 50:
            inner_text_color = "rgb(255, 140, 50)"
        elif percentage < 75:
            inner_text_color = "rgb(255, 200, 50)"
        else:
            inner_text_color = "rgb(120, 200, 100)"
    
    # Build inner text
    inner_parts = []
    if show_percentage:
        inner_parts.append(f'<div style="font-size: {text_size + 4}px; color: {inner_text_color};">{percentage}%</div>')
    if show_numbers:
        inner_parts.append(f'<div style="font-size: {text_size - 2}px; margin-top: 2px;">{done}/{total}</div>')
    
    # Build breakdown
    breakdown_lines = []
    if show_new:
        breakdown_lines.append(f"New: {data['new_remaining']}")
    if show_learning:
        breakdown_lines.append(f"Learn: {data['learning_remaining']}")
    if show_review:
        breakdown_lines.append(f"Review: {data['review_remaining']}")
    
    breakdown_bg = ""
    if breakdown_lines:
        if glass_effect:
            # TRUE glass: just blur, minimal tint
            breakdown_bg = f"""background: rgba(255, 255, 255, {glass_opacity * 0.15});
                backdrop-filter: blur({glass_blur}px) saturate(180%) brightness(1.1);
                -webkit-backdrop-filter: blur({glass_blur}px) saturate(180%) brightness(1.1);
                border: 1px solid rgba(255, 255, 255, 0.2);
                box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);"""
        else:
            breakdown_bg = "background: rgba(255, 255, 255, 0.9);"
    
    # Calculate breakdown height
    circle_segments = ""
    circle_stroke = None
    
    if gradient_type == "traffic":
        num_segments = 20
        for i in range(num_segments):
            seg_percentage = (i / num_segments) * 100
            if seg_percentage <= percentage:
                if seg_percentage < 25:
                    color = "rgb(220, 50, 50)"
                elif seg_percentage < 50:
                    ratio = (seg_percentage - 25) / 25
                    g = int(50 + (140 - 50) * ratio)
                    color = f"rgb(220, {g}, 50)"
                elif seg_percentage < 75:
                    ratio = (seg_percentage - 50) / 25
                    r = int(255 - (35 * ratio))
                    g = int(140 + (60 * ratio))
                    color = f"rgb({r}, {g}, 50)"
                else:
                    ratio = (seg_percentage - 75) / 25
                    r = int(220 - (100 * ratio))
                    g = 200
                    b = int(50 + (50 * ratio))
                    color = f"rgb({r}, {g}, {b})"
                
                seg_length = circumference / num_segments
                offset = circumference - (i * seg_length) - seg_length
                
                circle_segments += f'''
                <circle
                    cx="{radius}"
                    cy="{radius}"
                    r="{radius - 5}"
                    fill="none"
                    stroke="{color}"
                    stroke-width="8"
                    stroke-dasharray="{seg_length} {circumference - seg_length}"
                    stroke-dashoffset="{offset}"
                    stroke-linecap="round"
                />
                '''
    else:
        circle_stroke = solid_color if solid_color else base_circle_color
    
    # SVG gradient definition
    svg_gradient = ""
    if gradient_type == "fade" and gradient_css:
        svg_gradient = f'<defs><linearGradient id="fadeGrad" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" style="stop-color:{base_circle_color};stop-opacity:0.5" /><stop offset="100%" style="stop-color:{base_circle_color};stop-opacity:1" /></linearGradient></defs>'
        circle_stroke = "url(#fadeGrad)"
    
    # Generate breakdown background style
    breakdown_bg = ""
    if breakdown_lines:
        if glass_effect:
            # TRUE glass: just blur, minimal tint
            breakdown_bg = f"""background: rgba(255, 255, 255, {glass_opacity * 0.15});
                backdrop-filter: blur({glass_blur}px) saturate(180%) brightness(1.1);
                -webkit-backdrop-filter: blur({glass_blur}px) saturate(180%) brightness(1.1);
                border: 1px solid rgba(255, 255, 255, 0.2);
                box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);"""
        else:
            breakdown_bg = "background: rgba(255, 255, 255, 0.9);"
    
    # Calculate breakdown height with gap
    breakdown_height = 44 if breakdown_lines else 0  # Increased for more gap
    total_height = size + breakdown_height
    
    return f"""
    <div id="progress-circle-container" style="
        position: fixed;
        {position_styles.get(position, position_styles['top-right'])}
        width: {size}px;
        height: {total_height}px;
        z-index: 10000;
        pointer-events: none;
    ">
        <!-- Circle SVG with margin-bottom for spacing -->
        <div style="position: relative; width: {size}px; height: {size}px; margin-bottom: 14px;">
            <svg width="{size}" height="{size}" style="transform: rotate(-90deg);">
                {svg_gradient}
                <circle
                    cx="{radius}"
                    cy="{radius}"
                    r="{radius - 5}"
                    fill="none"
                    stroke="{bg_color}"
                    stroke-width="8"
                />
                {circle_segments if circle_stroke is None else f'''<circle
                    cx="{radius}"
                    cy="{radius}"
                    r="{radius - 5}"
                    fill="none"
                    stroke="{circle_stroke}"
                    stroke-width="8"
                    stroke-dasharray="{circumference}"
                    stroke-dashoffset="{stroke_dashoffset}"
                    stroke-linecap="round"
                    style="transition: stroke-dashoffset 0.3s ease-out, stroke 0.3s ease-out;"
                />'''}
            </svg>
            
            <!-- Inner text -->
            <div style="
                position: absolute;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%);
                text-align: center;
                font-weight: bold;
                line-height: 1.2;
                pointer-events: none;
            ">
                {''.join(inner_parts)}
            </div>
            
            <!-- Gear icon - positioned at top-right corner -->
            <div id="progress-reschedule-btn-circle" onclick="pycmd('progressbar:reschedule')" style="
                position: absolute;
                top: -2px;
                right: -2px;
                width: 12px;
                height: 12px;
                cursor: pointer;
                opacity: 0.6;
                transition: opacity 0.2s;
                z-index: 100;
                pointer-events: auto;
            " onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0.6'">
                <svg width="12" height="12" viewBox="0 0 16 16" fill="{text_color}">
                    <path d="M8 4.754a3.246 3.246 0 1 0 0 6.492 3.246 3.246 0 0 0 0-6.492zM5.754 8a2.246 2.246 0 1 1 4.492 0 2.246 2.246 0 0 1-4.492 0z"/>
                    <path d="M9.796 1.343c-.527-1.79-3.065-1.79-3.592 0l-.094.319a.873.873 0 0 1-1.255.52l-.292-.16c-1.64-.892-3.433.902-2.54 2.541l.159.292a.873.873 0 0 1-.52 1.255l-.319.094c-1.79.527-1.79 3.065 0 3.592l.319.094a.873.873 0 0 1 .52 1.255l-.16.292c-.892 1.64.901 3.434 2.541 2.54l.292-.159a.873.873 0 0 1 1.255.52l.094.319c.527 1.79 3.065 1.79 3.592 0l.094-.319a.873.873 0 0 1 1.255-.52l.292.16c1.64.893 3.434-.902 2.54-2.541l-.159-.292a.873.873 0 0 1 .52-1.255l.319-.094c1.79-.527 1.79-3.065 0-3.592l-.319-.094a.873.873 0 0 1-.52-1.255l.16-.292c.893-1.64-.902-3.433-2.541-2.54l-.292.159a.873.873 0 0 1-1.255-.52l-.094-.319z"/>
                </svg>
            </div>
        </div>
        
        <!-- Breakdown below circle -->
        {f'''<div style="
            position: absolute;
            bottom: 0;
            left: 50%;
            transform: translateX(-50%);
            color: {text_color};
            font-size: {text_size - 2}px;
            font-weight: bold;
            {breakdown_bg}
            padding: 4px 8px;
            border-radius: 6px;
            white-space: nowrap;
            pointer-events: none;
            text-align: center;
        ">{"<br>".join(breakdown_lines)}</div>''' if breakdown_lines else ''}
    </div>
    """

def inject_progress_bar(web_content, context):
    """Inject progress bar into reviewer, overview, and deck browser"""
    from aqt.overview import Overview
    from aqt.deckbrowser import DeckBrowser
    
    config = get_config()
    if not config.get("enabled", True):
        return
    
    is_review = isinstance(context, Reviewer)
    is_overview = isinstance(context, Overview)
    is_main = isinstance(context, DeckBrowser)
    
    display_on_review = config.get("display_on_review", True)
    display_on_home = config.get("display_on_home", True)
    display_on_main = config.get("display_on_main", True)
    
    if is_review and not display_on_review:
        return
    if is_overview and not display_on_home:
        return
    if is_main and not display_on_main:
        return
    
    if is_review or is_overview or is_main:
        progress_html = get_progress_html()
        web_content.body += progress_html

def handle_pycmd(handled, message, context):
    """Handle pycmd messages from the progress bar"""
    if message == "progressbar:reschedule":
        show_reschedule_dialog()
        return (True, None)
    return handled

def show_reschedule_dialog():
    """Show the reschedule dialog"""
    dialog = RescheduleDialog(mw)
    dialog.exec()

def on_reviewer_did_answer_card(reviewer, card, ease):
    """Update progress when a card is answered"""
    if not reviewer or not reviewer.web:
        return
    
    # Wait a moment for the database to update, then refresh just the progress bar
    def update_progress():
        if not reviewer.web:
            return
        
        # Generate fresh progress HTML
        progress_html = get_progress_html()
        
        # Remove old progress bar and inject new one
        js_code = f"""
        (function() {{
            // Remove old progress elements
            var oldBox = document.getElementById('progress-stats-box');
            var oldCircle = document.getElementById('progress-circle-container');
            if (oldBox) oldBox.remove();
            if (oldCircle) oldCircle.remove();
            
            // Inject new progress HTML
            var temp = document.createElement('div');
            temp.innerHTML = `{progress_html.replace('`', '\\`').replace('\\', '\\\\')}`;
            while (temp.firstChild) {{
                document.body.appendChild(temp.firstChild);
            }}
        }})();
        """
        
        try:
            reviewer.web.eval(js_code)
        except:
            pass
    
    # Small delay to let database update
    QTimer.singleShot(100, update_progress)

class TagPickerWidget(QWidget):
    """
    Searchable tag list with 300ms debounce and multi-select.

    Use & in the search box to AND terms (e.g. "neuro & pharm").
    Double-click a result to add it to the selected list.
    Click a selected item to remove it.
    """

    def __init__(self, parent=None, current_tags=None):
        super().__init__(parent)
        self._all_tags = sorted(mw.col.tags.all())
        self._selected = list(current_tags or [])
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._do_filter)
        self._setup_ui()

    @staticmethod
    def _matches(text, query):
        terms = [t.strip().lower() for t in query.split("&") if t.strip()]
        return all(t in text.lower() for t in terms)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search tags… (use & for AND, double-click to add)")
        self.search_box.textChanged.connect(lambda: self._timer.start(300))
        layout.addWidget(self.search_box)

        self.results_list = QListWidget()
        self.results_list.setMaximumHeight(130)
        self.results_list.itemDoubleClicked.connect(self._on_add)
        layout.addWidget(self.results_list)

        selected_header = QLabel("Selected tags  (click to remove):")
        selected_header.setStyleSheet("color: #888; font-size: 10px;")
        layout.addWidget(selected_header)

        self.selected_list = QListWidget()
        self.selected_list.setMaximumHeight(70)
        self.selected_list.itemClicked.connect(self._on_remove)
        layout.addWidget(self.selected_list)

        self._do_filter()
        self._refresh_selected()

    def _do_filter(self):
        query = self.search_box.text().strip()
        self.results_list.clear()
        if query:
            matches = [t for t in self._all_tags if self._matches(t, query)]
        else:
            matches = self._all_tags[:100]
        for tag in matches:
            self.results_list.addItem(QListWidgetItem(tag))

    def _on_add(self, item):
        tag = item.text()
        if tag and tag not in self._selected:
            self._selected.append(tag)
            self._refresh_selected()

    def _on_remove(self, item):
        tag = item.text()
        if tag in self._selected:
            self._selected.remove(tag)
            self._refresh_selected()

    def _refresh_selected(self):
        self.selected_list.clear()
        for tag in self._selected:
            self.selected_list.addItem(QListWidgetItem(tag))

    def get_selected(self):
        return list(self._selected)


class DeckPickerWidget(QWidget):
    """
    Hierarchical deck browser + search with 300ms debounce and multi-select.

    Browse mode: top-level parents shown. ▶ = has children, single-click to
    drill in. ← Back returns one level. Double-click any selectable deck to add.

    Search mode: type to filter (use & for AND terms). Results grouped under
    bold parent headers. Double-click any row to add.

    Selected decks shown below — click to remove.
    """

    def __init__(self, parent=None, current_decks=None):
        super().__init__(parent)
        self._all_decks = sorted([d.name for d in mw.col.decks.all_names_and_ids()])
        self._selected = list(current_decks or [])
        self._browse_path = []
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._do_filter)
        self._setup_ui()

    @staticmethod
    def _matches(text, query):
        terms = [t.strip().lower() for t in query.split("&") if t.strip()]
        return all(t in text.lower() for t in terms)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search decks… (use & for AND, double-click to add)")
        self.search_box.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.search_box)

        self.browse_list = QListWidget()
        self.browse_list.setMaximumHeight(160)
        self.browse_list.itemClicked.connect(self._on_browse_click)
        self.browse_list.itemDoubleClicked.connect(self._on_browse_double_click)
        layout.addWidget(self.browse_list)

        selected_header = QLabel("Selected decks  (click to remove):")
        selected_header.setStyleSheet("color: #888; font-size: 10px;")
        layout.addWidget(selected_header)

        self.selected_list = QListWidget()
        self.selected_list.setMaximumHeight(70)
        self.selected_list.itemClicked.connect(self._on_remove)
        layout.addWidget(self.selected_list)

        self._show_browse_level()
        self._refresh_selected()

    # ── helpers ──────────────────────────────────────────────────────────

    def _has_children(self, deck_name):
        return any(d.startswith(deck_name + "::") for d in self._all_decks)

    def _direct_children(self, parent):
        prefix = parent + "::"
        seen = set()
        result = []
        for d in self._all_decks:
            if d.startswith(prefix):
                child = prefix + d[len(prefix):].split("::")[0]
                if child not in seen:
                    seen.add(child)
                    result.append(child)
        return sorted(result)

    def _add_deck(self, deck_name):
        if deck_name and deck_name not in self._selected:
            self._selected.append(deck_name)
            self._refresh_selected()

    def _refresh_selected(self):
        self.selected_list.clear()
        for deck in self._selected:
            self.selected_list.addItem(QListWidgetItem(deck))

    def _on_remove(self, item):
        deck = item.text()
        if deck in self._selected:
            self._selected.remove(deck)
            self._refresh_selected()

    # ── browse mode ───────────────────────────────────────────────────────

    def _on_text_changed(self, text):
        if text.strip():
            self._timer.start(300)
        else:
            self._timer.stop()
            self._browse_path = []
            self._show_browse_level()

    def _show_browse_level(self):
        self.browse_list.clear()

        if self._browse_path:
            back = QListWidgetItem("← Back")
            back.setData(Qt.ItemDataRole.UserRole, ("back", None))
            back.setForeground(Qt.GlobalColor.blue)
            self.browse_list.addItem(back)

            current_parent = self._browse_path[-1]
            leaf = current_parent.split("::")[-1]
            use_all = QListWidgetItem(f"  📁 {leaf}  — select entire deck")
            use_all.setData(Qt.ItemDataRole.UserRole, ("select", current_parent))
            use_all.setForeground(Qt.GlobalColor.darkGray)
            use_all.setToolTip(current_parent)
            self.browse_list.addItem(use_all)

            decks_to_show = self._direct_children(current_parent)
        else:
            seen = set()
            decks_to_show = []
            for d in self._all_decks:
                top = d.split("::")[0]
                if top not in seen:
                    seen.add(top)
                    decks_to_show.append(top)

        for deck in decks_to_show:
            leaf = deck.split("::")[-1]
            if self._has_children(deck):
                item = QListWidgetItem(f"▶  {leaf}")
                item.setData(Qt.ItemDataRole.UserRole, ("expand", deck))
            else:
                item = QListWidgetItem(f"    {leaf}")
                item.setData(Qt.ItemDataRole.UserRole, ("select", deck))
            item.setToolTip(deck)
            self.browse_list.addItem(item)

    def _on_browse_click(self, item):
        """Single click handles navigation only (expand / back)."""
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        action, value = data
        if action == "expand":
            self._browse_path.append(value)
            self.search_box.clear()
            self._show_browse_level()
        elif action == "back":
            self._browse_path.pop()
            self._show_browse_level()

    def _on_browse_double_click(self, item):
        """Double-click adds the deck to the selection."""
        data = item.data(Qt.ItemDataRole.UserRole)
        if data and data[0] == "select":
            self._add_deck(data[1])

    # ── search / filter mode ──────────────────────────────────────────────

    def _do_filter(self):
        query = self.search_box.text().strip()
        if not query:
            return

        matches = [d for d in self._all_decks if self._matches(d, query)]
        self.browse_list.clear()

        shown_parents = set()
        for deck in matches:
            parts = deck.split("::")
            top = parts[0]

            if top not in shown_parents:
                shown_parents.add(top)
                header = QListWidgetItem(f"📁 {top}")
                header.setData(Qt.ItemDataRole.UserRole, ("select", top))
                font = header.font()
                font.setBold(True)
                header.setFont(font)
                header.setToolTip(top)
                self.browse_list.addItem(header)

            if len(parts) > 1:
                indent = "  " * (len(parts) - 1)
                item = QListWidgetItem(f"{indent}{parts[-1]}")
                item.setData(Qt.ItemDataRole.UserRole, ("select", deck))
                item.setToolTip(deck)
                self.browse_list.addItem(item)

    def get_selected(self):
        return list(self._selected)


# Reschedule Dialog with Tabs
class RescheduleDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Card Management")
        self.setMinimumWidth(650)  # Increased from 500
        self.setMinimumHeight(500)  # Increased from 400
        
        main_layout = QVBoxLayout()
        
        # Create tab widget
        self.tabs = QTabWidget()
        
        # Tab 1: Reschedule (existing functionality)
        reschedule_tab = QWidget()
        self.setup_reschedule_tab(reschedule_tab)
        self.tabs.addTab(reschedule_tab, "Reschedule Cards")
        
        # Tab 2: Batch Unsuspend (new functionality)
        unsuspend_tab = QWidget()
        self.setup_unsuspend_tab(unsuspend_tab)
        self.tabs.addTab(unsuspend_tab, "Batch Unsuspend")
        
        main_layout.addWidget(self.tabs)
        self.setLayout(main_layout)
    
    def setup_reschedule_tab(self, tab):
        """Setup the reschedule cards tab (original functionality)"""
        layout = QVBoxLayout()
        
        # Instructions
        info_label = QLabel("Delay cards forward or bring them back")
        info_label.setStyleSheet("font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(info_label)
        
        # Days input
        days_layout = QHBoxLayout()
        days_layout.addWidget(QLabel("Days to delay:"))
        self.days_spin = QSpinBox()
        self.days_spin.setRange(-365, 365)
        self.days_spin.setValue(1)
        self.days_spin.setMinimumWidth(100)
        days_layout.addWidget(self.days_spin)
        days_layout.addStretch()
        layout.addLayout(days_layout)
        
        hint_label = QLabel("💡 Negative numbers will bring days forward")
        hint_label.setStyleSheet("color: gray; font-size: 11px; margin-bottom: 15px;")
        layout.addWidget(hint_label)
        
        # Deck selection with tree
        deck_label = QLabel("Select decks to delay:")
        deck_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(deck_label)
        
        self.deck_tree = QTreeWidget()
        self.deck_tree.setHeaderHidden(True)
        self.deck_tree.setMaximumHeight(250)
        
        # Build deck tree
        all_decks = mw.col.decks.all_names_and_ids()
        deck_dict = {}
        
        # First pass: create all items
        for deck_info in sorted(all_decks, key=lambda d: d.name):
            deck_name = deck_info.name
            deck_id = deck_info.id
            parts = deck_name.split("::")
            
            item = QTreeWidgetItem([parts[-1]])  # Show only last part
            item.setData(0, Qt.ItemDataRole.UserRole, deck_id)
            item.setData(1, Qt.ItemDataRole.UserRole, deck_name)  # Full name
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Unchecked)
            
            deck_dict[deck_name] = item
        
        # Second pass: build hierarchy
        root_items = []
        for deck_name, item in deck_dict.items():
            parts = deck_name.split("::")
            if len(parts) == 1:
                root_items.append(item)
            else:
                parent_name = "::".join(parts[:-1])
                if parent_name in deck_dict:
                    deck_dict[parent_name].addChild(item)
                else:
                    root_items.append(item)
        
        for item in root_items:
            self.deck_tree.addTopLevelItem(item)
        
        layout.addWidget(self.deck_tree)
        
        # Select all button
        select_all_btn = QPushButton("Check All Decks")
        select_all_btn.clicked.connect(self.select_all_decks)
        layout.addWidget(select_all_btn)
        
        # Buttons
        button_layout = QHBoxLayout()
        delay_btn = QPushButton("Delay Cards")
        delay_btn.clicked.connect(self.do_delay)
        delay_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 8px;")
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        
        button_layout.addWidget(delay_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
        
        tab.setLayout(layout)
    
    def setup_unsuspend_tab(self, tab):
        """Setup the batch unsuspend tab"""
        layout = QVBoxLayout()
        
        # Get config for unsuspend rules
        config = get_config()
        if "UnsuspendRules" not in config:
            config["UnsuspendRules"] = {}
            save_config(config)
        
        # Rule list area
        rule_label = QLabel("Unsuspend Rules:")
        rule_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(rule_label)
        
        # Scroll area for rules
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(250)
        
        rules_widget = QWidget()
        self.rules_layout = QVBoxLayout()
        rules_widget.setLayout(self.rules_layout)
        scroll.setWidget(rules_widget)
        
        layout.addWidget(scroll)

        # Buttons
        button_layout = QHBoxLayout()

        add_rule_btn = QPushButton("Add Rule")
        add_rule_btn.clicked.connect(self._show_rule_dialog)

        unsuspend_btn = QPushButton("Unsuspend Selected")
        unsuspend_btn.clicked.connect(self.batch_unsuspend)
        unsuspend_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 8px;")

        button_layout.addWidget(add_rule_btn)
        button_layout.addWidget(unsuspend_btn)
        layout.addLayout(button_layout)

        self.total_cards_label = QLabel()
        self.total_cards_label.setStyleSheet(
            "font-size: 13px; font-weight: bold; padding: 6px 0px;"
        )
        layout.addWidget(self.total_cards_label)

        # Populate rules (must be after total_cards_label is created)
        self.refresh_unsuspend_rules()

        tab.setLayout(layout)
    
    def select_all_decks(self):
        """Check all decks in the tree"""
        def check_item(item):
            item.setCheckState(0, Qt.CheckState.Checked)
            for i in range(item.childCount()):
                check_item(item.child(i))
        
        root = self.deck_tree.invisibleRootItem()
        for i in range(root.childCount()):
            check_item(root.child(i))
    
    def get_checked_decks(self):
        """Get all checked deck IDs"""
        checked_ids = []
        
        def collect_checked(item):
            if item.checkState(0) == Qt.CheckState.Checked:
                deck_id = item.data(0, Qt.ItemDataRole.UserRole)
                checked_ids.append(deck_id)
            for i in range(item.childCount()):
                collect_checked(item.child(i))
        
        root = self.deck_tree.invisibleRootItem()
        for i in range(root.childCount()):
            collect_checked(root.child(i))
        
        return checked_ids
    
    def do_delay(self):
        """Perform the delay - EXACTLY like reference code"""
        days_to_delay = self.days_spin.value()
        
        if days_to_delay == 0:
            showInfo("Please enter a non-zero number of days.")
            return
        
        # Get selected deck IDs
        deck_ids = self.get_checked_decks()
        
        if not deck_ids:
            showInfo("Please select at least one deck.")
            return
        
        # Get all cards from selected decks (including children)
        all_cids = []
        deckManager = mw.col.decks
        for did in deck_ids:
            cids = deckManager.cids(did, children=True)
            all_cids.extend(cids)
        
        if not all_cids:
            tooltip("Selected decks contain no cards.")
            return
        
        # Create card objects
        cards = [Card(mw.col, cid) for cid in all_cids]
        
        # Delay cards EXACTLY like the reference code
        DUE = 2
        SUSPENDED = -1
        IS_AT_LEAST_VERSION_23 = pointVersion() >= 231000
        
        card_count = 0
        for card in cards:
            if card.type == DUE and card.queue != SUSPENDED:
                adjusted_due_date = card.due + days_to_delay
                card.due = adjusted_due_date
                if IS_AT_LEAST_VERSION_23:
                    mw.col.update_card(card)
                else:  # older versions
                    card.flush()
                card_count += 1
        
        # Save all decks
        for did in deck_ids:
            deck = deckManager.get(did)
            mw.col.decks.save(deck)
        
        mw.reset()
        self.accept()
        
        # Tooltip
        if days_to_delay < 0:
            main_text = "Deck brought forward by:"
            days_text = "days" if abs(days_to_delay) != 1 else "day"
        else:
            main_text = "Delayed deck by:"
            days_text = "days" if days_to_delay != 1 else "day"
        
        tooltip(f"{main_text} {abs(days_to_delay)} {days_text}")
    
    def _update_total_label(self):
        config = get_config()
        rules = config.get("UnsuspendRules", {})
        total = sum(
            r.get("cards_count", 0)
            for r in rules.values()
            if r.get("active", True)
        )
        self.total_cards_label.setText(f"Total new cards on next unsuspend: {total}")

    def refresh_unsuspend_rules(self):
        """Refresh the list of unsuspend rules"""
        # Clear existing widgets
        while self.rules_layout.count():
            item = self.rules_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        config = get_config()
        rules = config.get("UnsuspendRules", {})

        if not rules:
            no_rules_label = QLabel("No rules yet. Click 'Add Rule' to create one.")
            no_rules_label.setStyleSheet("color: gray; font-style: italic;")
            self.rules_layout.addWidget(no_rules_label)
        else:
            for rule_name, rule_data in rules.items():
                rule_widget = self.create_rule_widget(rule_name, rule_data)
                self.rules_layout.addWidget(rule_widget)

        self.rules_layout.addStretch()
        self._update_total_label()
    
    def create_rule_widget(self, rule_name, rule_data):
        """Create a widget for a single unsuspend rule"""
        widget = QWidget()
        # Changed from #f0f0f0 (light gray) to #3a3a3a (dark gray) for better visibility
        widget.setStyleSheet("background-color: #3a3a3a; border-radius: 5px; padding: 5px; margin: 2px;")
        layout = QHBoxLayout()
        layout.setContentsMargins(10, 5, 10, 5)
        
        # Checkbox for active/inactive
        checkbox = QCheckBox()
        checkbox.setChecked(rule_data.get("active", True))
        checkbox.stateChanged.connect(lambda state, rn=rule_name: self.toggle_rule(rn, state == Qt.CheckState.Checked.value))
        layout.addWidget(checkbox)
        
        # Rule info — support both old string fields and new list fields
        tags = rule_data.get("tags") or ([rule_data["tag"]] if rule_data.get("tag") else [])
        decks = rule_data.get("decks") or ([rule_data["deck"]] if rule_data.get("deck") else [])
        cards_count = rule_data.get("cards_count", 0)

        info_parts = [f"<b>{rule_name}</b>"]
        if tags:
            info_parts.append("Tags: " + ", ".join(tags))
        if decks:
            info_parts.append("Decks: " + ", ".join(decks))
        info_parts.append(f"Cards: {cards_count}")
        
        info_label = QLabel(" - ".join(info_parts))
        layout.addWidget(info_label)
        
        layout.addStretch()
        
        # Edit button
        edit_btn = QPushButton("Edit")
        edit_btn.setMaximumWidth(60)
        edit_btn.clicked.connect(lambda _, rn=rule_name: self._show_rule_dialog(rn))
        layout.addWidget(edit_btn)
        
        # Delete button
        delete_btn = QPushButton("Delete")
        delete_btn.setMaximumWidth(70)
        delete_btn.clicked.connect(lambda _, rn=rule_name: self.delete_unsuspend_rule(rn))
        layout.addWidget(delete_btn)
        
        widget.setLayout(layout)
        return widget
    
    def _show_rule_dialog(self, existing_rule_name=None):
        """Add a new rule (existing_rule_name=None) or edit an existing one."""
        config = get_config()
        rule_data = config.get("UnsuspendRules", {}).get(existing_rule_name, {}) if existing_rule_name else {}

        title = f"Edit Rule: {existing_rule_name}" if existing_rule_name else "Add Unsuspend Rule"
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setMinimumWidth(460)
        layout = QVBoxLayout()

        # Rule name
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Rule Name:"))
        name_input = QLineEdit()
        name_input.setText(existing_rule_name or "")
        name_layout.addWidget(name_input)
        layout.addLayout(name_layout)

        # Tag picker — support old single-string "tag" and new list "tags"
        existing_tags = rule_data.get("tags") or ([rule_data["tag"]] if rule_data.get("tag") else [])
        layout.addWidget(QLabel("Tags (optional):"))
        tag_picker = TagPickerWidget(current_tags=existing_tags)
        layout.addWidget(tag_picker)

        # Deck picker — support old single-string "deck" and new list "decks"
        existing_decks = rule_data.get("decks") or ([rule_data["deck"]] if rule_data.get("deck") else [])
        layout.addWidget(QLabel("Decks (optional):"))
        deck_picker = DeckPickerWidget(current_decks=existing_decks)
        layout.addWidget(deck_picker)

        note_label = QLabel("Specify a tag, deck, or both to filter which cards get unsuspended.")
        note_label.setStyleSheet("color: gray; font-size: 10px; font-style: italic;")
        layout.addWidget(note_label)

        # Cards count
        cards_layout = QHBoxLayout()
        cards_layout.addWidget(QLabel("Cards to unsuspend:"))
        cards_spin = QSpinBox()
        cards_spin.setRange(1, 999)
        cards_spin.setValue(rule_data.get("cards_count", 10))
        cards_layout.addWidget(cards_spin)
        layout.addLayout(cards_layout)

        # Buttons
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Save")
        cancel_btn = QPushButton("Cancel")

        def save_rule():
            new_name = name_input.text().strip()
            if not new_name:
                showInfo("Please enter a rule name.")
                return

            tags = tag_picker.get_selected()
            decks = deck_picker.get_selected()

            if not tags and not decks:
                showInfo("Please specify at least one tag or deck.")
                return

            cfg = get_config()
            if "UnsuspendRules" not in cfg:
                cfg["UnsuspendRules"] = {}

            # On add: reject duplicate names
            if not existing_rule_name and new_name in cfg["UnsuspendRules"]:
                showInfo("A rule with this name already exists.")
                return

            # On edit: remove old entry (handles renames)
            if existing_rule_name and existing_rule_name in cfg["UnsuspendRules"]:
                del cfg["UnsuspendRules"][existing_rule_name]

            cfg["UnsuspendRules"][new_name] = {
                "tags": tags,
                "decks": decks,
                "cards_count": cards_spin.value(),
                "active": rule_data.get("active", True),
            }
            save_config(cfg)
            self.refresh_unsuspend_rules()
            dialog.accept()

        save_btn.clicked.connect(save_rule)
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        dialog.setLayout(layout)
        dialog.exec()
    
    def delete_unsuspend_rule(self, rule_name):
        """Delete an unsuspend rule"""
        config = get_config()
        if rule_name in config.get("UnsuspendRules", {}):
            del config["UnsuspendRules"][rule_name]
            save_config(config)
            self.refresh_unsuspend_rules()
    
    def toggle_rule(self, rule_name, active):
        """Toggle rule active state"""
        config = get_config()
        if rule_name in config.get("UnsuspendRules", {}):
            config["UnsuspendRules"][rule_name]["active"] = active
            save_config(config)
            self._update_total_label()
    
    def batch_unsuspend(self):
        """Unsuspend cards based on active rules"""
        config = get_config()
        rules = config.get("UnsuspendRules", {})
        
        active_rules = {name: data for name, data in rules.items() if data.get("active", True)}
        
        if not active_rules:
            showInfo("No active rules selected.")
            return
        
        mw.checkpoint("Batch Unsuspend Cards")
        
        results = []
        for rule_name, rule_data in active_rules.items():
            # Support both old single-string fields and new list fields
            tags = rule_data.get("tags") or ([rule_data["tag"]] if rule_data.get("tag") else [])
            decks = rule_data.get("decks") or ([rule_data["deck"]] if rule_data.get("deck") else [])
            tags = [t.strip() for t in tags if t.strip()]
            decks = [d.strip() for d in decks if d.strip()]
            n = rule_data.get("cards_count", 0)

            # Build search query: tags are AND, decks are OR
            search_parts = []
            for tag in tags:
                search_parts.append(f'tag:"{tag}"')
            if len(decks) == 1:
                search_parts.append(f'deck:"{decks[0]}"')
            elif len(decks) > 1:
                search_parts.append("(" + " OR ".join(f'deck:"{d}"' for d in decks) + ")")
            search_parts.append("is:suspended")
            search_query = " ".join(search_parts)
            
            # Find suspended cards matching criteria
            card_ids = mw.col.findCards(search_query)
            card_ids.sort()  # Sort by creation date
            
            n_available = len(card_ids)
            
            if n_available == 0:
                results.append(f"{rule_name}: No suspended cards found")
            elif n_available < n:
                mw.col.sched.unsuspendCards(card_ids[:n_available])
                results.append(f"{rule_name}: Unsuspended {n_available}/{n} cards")
            else:
                mw.col.sched.unsuspendCards(card_ids[:n])
                results.append(f"{rule_name}: Unsuspended {n} cards")
        
        mw.reset()
        self.accept()
        
        # Show results
        showInfo("\n".join(results))
        
        self.accept()

def show_reschedule_dialog():
    """Show the reschedule dialog"""
    dialog = RescheduleDialog(mw)
    dialog.exec()

# Settings Dialog
class ProgressBarSettings(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = get_config()
        self.setWindowTitle("Progress Bar Settings")
        self.setMinimumWidth(500)
        
        layout = QVBoxLayout()
        
        # Scrollable area
        from aqt.qt import QScrollArea, QWidget
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        
        # Display Style
        style_group = QGroupBox("Display Style")
        style_layout = QVBoxLayout()
        
        style_row = QHBoxLayout()
        style_row.addWidget(QLabel("Style:"))
        self.style_combo = QComboBox()
        self.style_combo.addItems(["box", "circle"])
        current_style = "box" if self.config.get("style") == "bar" else self.config.get("style", "bar")
        self.style_combo.setCurrentText(current_style)
        self.style_combo.currentTextChanged.connect(self.update_position_options)
        style_row.addWidget(self.style_combo)
        style_layout.addLayout(style_row)
        
        style_group.setLayout(style_layout)
        scroll_layout.addWidget(style_group)
        
        # Position
        position_group = QGroupBox("Position")
        position_layout = QVBoxLayout()
        
        pos_row = QHBoxLayout()
        pos_row.addWidget(QLabel("Position:"))
        self.position_combo = QComboBox()
        # Will populate after widgets are created
        pos_row.addWidget(self.position_combo)
        position_layout.addLayout(pos_row)
        
        position_group.setLayout(position_layout)
        scroll_layout.addWidget(position_group)
        
        # Theme & Effects
        theme_group = QGroupBox("Theme & Effects")
        theme_layout = QVBoxLayout()
        
        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("Theme Preset:"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["light", "dark", "nord", "dracula", "solarized_dark", "monokai", "custom"])
        self.theme_combo.setCurrentText(self.config.get("theme", "light"))
        theme_row.addWidget(self.theme_combo)
        theme_layout.addLayout(theme_row)
        
        self.glass_effect_check = QCheckBox("Enable Glass Effect (Frosted/Liquid Glass)")
        self.glass_effect_check.setChecked(self.config.get("glass_effect", False))
        theme_layout.addWidget(self.glass_effect_check)
        
        glass_opacity_row = QHBoxLayout()
        glass_opacity_row.addWidget(QLabel("Glass Opacity:"))
        self.glass_opacity_spin = QSpinBox()
        self.glass_opacity_spin.setRange(10, 100)
        self.glass_opacity_spin.setValue(int(self.config.get("glass_opacity", 0.7) * 100))
        self.glass_opacity_spin.setSuffix("%")
        glass_opacity_row.addWidget(self.glass_opacity_spin)
        theme_layout.addLayout(glass_opacity_row)
        
        glass_blur_row = QHBoxLayout()
        glass_blur_row.addWidget(QLabel("Glass Blur:"))
        self.glass_blur_spin = QSpinBox()
        self.glass_blur_spin.setRange(0, 30)
        self.glass_blur_spin.setValue(self.config.get("glass_blur", 15))
        self.glass_blur_spin.setSuffix("px")
        glass_blur_row.addWidget(self.glass_blur_spin)
        theme_layout.addLayout(glass_blur_row)
        
        # Text brightness control
        text_brightness_row = QHBoxLayout()
        text_brightness_row.addWidget(QLabel("Text Brightness:"))
        self.text_brightness_spin = QSpinBox()
        self.text_brightness_spin.setRange(0, 255)
        self.text_brightness_spin.setValue(self.config.get("text_brightness", 255))
        self.text_brightness_spin.setToolTip("255 = full white, 0 = black. Adjust for better visibility on backgrounds.")
        text_brightness_row.addWidget(self.text_brightness_spin)
        theme_layout.addLayout(text_brightness_row)
        
        theme_group.setLayout(theme_layout)
        scroll_layout.addWidget(theme_group)
        
        # Appearance
        appearance_group = QGroupBox("Appearance")
        appearance_layout = QVBoxLayout()
        
        # Bar settings
        self.bar_settings_widget = QGroupBox("Box Settings")
        bar_layout = QVBoxLayout()
        
        thickness_row = QHBoxLayout()
        thickness_row.addWidget(QLabel("Box Padding (px):"))
        self.thickness_spin = QSpinBox()
        self.thickness_spin.setRange(2, 30)
        self.thickness_spin.setValue(self.config.get("bar_thickness", 8))
        thickness_row.addWidget(self.thickness_spin)
        bar_layout.addLayout(thickness_row)
        
        bar_color_row = QHBoxLayout()
        bar_color_row.addWidget(QLabel("Box Color:"))
        self.bar_color_btn = QPushButton()
        self.bar_color = self.config.get("bar_color", "#FF69B4")
        self.bar_color_btn.setStyleSheet(f"background-color: {self.bar_color}; min-width: 100px;")
        self.bar_color_btn.clicked.connect(self.choose_bar_color)
        bar_color_row.addWidget(self.bar_color_btn)
        bar_layout.addLayout(bar_color_row)
        
        self.bar_settings_widget.setLayout(bar_layout)
        appearance_layout.addWidget(self.bar_settings_widget)
        
        # Circle settings
        self.circle_settings_widget = QGroupBox("Circle Settings")
        circle_layout = QVBoxLayout()
        
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Circle Size (px):"))
        self.size_spin = QSpinBox()
        self.size_spin.setRange(50, 150)
        self.size_spin.setValue(self.config.get("circle_size", 80))
        size_row.addWidget(self.size_spin)
        circle_layout.addLayout(size_row)
        
        circle_color_row = QHBoxLayout()
        circle_color_row.addWidget(QLabel("Circle Color:"))
        self.circle_color_btn = QPushButton()
        self.circle_color = self.config.get("circle_color", "#FF69B4")
        self.circle_color_btn.setStyleSheet(f"background-color: {self.circle_color}; min-width: 100px;")
        self.circle_color_btn.clicked.connect(self.choose_circle_color)
        circle_color_row.addWidget(self.circle_color_btn)
        circle_layout.addLayout(circle_color_row)
        
        self.circle_settings_widget.setLayout(circle_layout)
        appearance_layout.addWidget(self.circle_settings_widget)
        
        # Common settings
        bg_color_row = QHBoxLayout()
        bg_color_row.addWidget(QLabel("Background Color:"))
        self.bg_color_btn = QPushButton()
        self.bg_color = self.config.get("bar_background", "#E0E0E0")
        self.bg_color_btn.setStyleSheet(f"background-color: {self.bg_color}; min-width: 100px;")
        self.bg_color_btn.clicked.connect(self.choose_bg_color)
        bg_color_row.addWidget(self.bg_color_btn)
        appearance_layout.addLayout(bg_color_row)
        
        text_color_row = QHBoxLayout()
        text_color_row.addWidget(QLabel("Text Color:"))
        self.text_color_btn = QPushButton()
        self.text_color = self.config.get("text_color", "#000000")
        self.text_color_btn.setStyleSheet(f"background-color: {self.text_color}; min-width: 100px;")
        self.text_color_btn.clicked.connect(self.choose_text_color)
        text_color_row.addWidget(self.text_color_btn)
        appearance_layout.addLayout(text_color_row)
        
        text_size_row = QHBoxLayout()
        text_size_row.addWidget(QLabel("Text Size (px):"))
        self.text_size_spin = QSpinBox()
        self.text_size_spin.setRange(8, 24)
        self.text_size_spin.setValue(self.config.get("text_size", 12))
        text_size_row.addWidget(self.text_size_spin)
        appearance_layout.addLayout(text_size_row)
        
        gradient_row = QHBoxLayout()
        gradient_row.addWidget(QLabel("Gradient Type:"))
        self.gradient_combo = QComboBox()
        self.gradient_combo.addItems(["solid", "fade", "traffic"])
        self.gradient_combo.setCurrentText(self.config.get("gradient_type", "solid"))
        gradient_row.addWidget(self.gradient_combo)
        appearance_layout.addLayout(gradient_row)
        
        appearance_group.setLayout(appearance_layout)
        scroll_layout.addWidget(appearance_group)
        
        # Now that all widgets exist, update visibility and populate position options
        self.update_position_options()
        self.update_style_visibility()
        
        # Statistics Display
        stats_group = QGroupBox("Statistics Display")
        stats_layout = QVBoxLayout()
        
        self.show_percentage_check = QCheckBox("Show percentage")
        self.show_percentage_check.setChecked(self.config.get("show_percentage", True))
        stats_layout.addWidget(self.show_percentage_check)
        
        self.show_numbers_check = QCheckBox("Show done/total numbers")
        self.show_numbers_check.setChecked(self.config.get("show_numbers", True))
        stats_layout.addWidget(self.show_numbers_check)
        
        self.show_new_check = QCheckBox("Show new cards count")
        self.show_new_check.setChecked(self.config.get("show_new_count", True))
        stats_layout.addWidget(self.show_new_check)
        
        self.show_learning_check = QCheckBox("Show learning cards count")
        self.show_learning_check.setChecked(self.config.get("show_learning_count", True))
        stats_layout.addWidget(self.show_learning_check)
        
        self.show_review_check = QCheckBox("Show review cards count")
        self.show_review_check.setChecked(self.config.get("show_review_count", True))
        stats_layout.addWidget(self.show_review_check)
        
        stats_group.setLayout(stats_layout)
        scroll_layout.addWidget(stats_group)
        
        # Deck Selection
        deck_group = QGroupBox("Deck Selection")
        deck_layout = QVBoxLayout()
        deck_layout.addWidget(QLabel("Select decks to track (leave empty for all):"))
        
        self.deck_list = QListWidget()
        self.deck_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.deck_list.setMaximumHeight(150)
        
        all_decks = [d.name for d in mw.col.decks.all_names_and_ids()]
        for deck_name in all_decks:
            self.deck_list.addItem(deck_name)
        
        selected_decks = self.config.get("selected_decks", [])
        for i in range(self.deck_list.count()):
            item = self.deck_list.item(i)
            if item.text() in selected_decks:
                item.setSelected(True)
        
        deck_layout.addWidget(self.deck_list)
        deck_group.setLayout(deck_layout)
        scroll_layout.addWidget(deck_group)
        
        # New Cards
        new_cards_group = QGroupBox("New Cards")
        new_cards_layout = QVBoxLayout()
        
        self.include_new_check = QCheckBox("Include new cards in progress")
        self.include_new_check.setChecked(self.config.get("include_new_cards", True))
        new_cards_layout.addWidget(self.include_new_check)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Tracking mode:"))
        self.new_cards_mode_combo = QComboBox()
        self.new_cards_mode_combo.addItem("Goal-based (count toward a daily goal)", "goal")
        self.new_cards_mode_combo.addItem("Scheduler (same as learning & review)", "scheduler")
        current_mode = self.config.get("new_cards_mode", "goal")
        self.new_cards_mode_combo.setCurrentIndex(0 if current_mode == "goal" else 1)
        mode_row.addWidget(self.new_cards_mode_combo)
        new_cards_layout.addLayout(mode_row)

        self.goal_row_widget = QWidget()
        goal_row = QHBoxLayout(self.goal_row_widget)
        goal_row.setContentsMargins(0, 0, 0, 0)
        goal_row.addWidget(QLabel("Daily new cards goal:"))
        self.new_cards_goal_spin = QSpinBox()
        self.new_cards_goal_spin.setRange(1, 9999)
        self.new_cards_goal_spin.setValue(self.config.get("new_cards_goal", 20))
        goal_row.addWidget(self.new_cards_goal_spin)
        new_cards_layout.addWidget(self.goal_row_widget)
        self.goal_row_widget.setVisible(current_mode == "goal")

        self.new_cards_mode_combo.currentIndexChanged.connect(
            lambda: self.goal_row_widget.setVisible(
                self.new_cards_mode_combo.currentData() == "goal"
            )
        )

        new_cards_group.setLayout(new_cards_layout)
        scroll_layout.addWidget(new_cards_group)
        
        # Display Location
        display_group = QGroupBox("Display Location")
        display_layout = QVBoxLayout()
        
        self.display_main_check = QCheckBox("Show on main Anki home screen")
        self.display_main_check.setChecked(self.config.get("display_on_main", True))
        display_layout.addWidget(self.display_main_check)
        
        self.display_home_check = QCheckBox("Show on deck overview screen")
        self.display_home_check.setChecked(self.config.get("display_on_home", True))
        display_layout.addWidget(self.display_home_check)
        
        self.display_review_check = QCheckBox("Show during reviews")
        self.display_review_check.setChecked(self.config.get("display_on_review", True))
        display_layout.addWidget(self.display_review_check)
        
        display_group.setLayout(display_layout)
        scroll_layout.addWidget(display_group)
        
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        # Debug button
        debug_btn = QPushButton("Show Debug Info")
        debug_btn.clicked.connect(self.show_debug_info)
        debug_btn.setStyleSheet("background-color: #FFA500; color: white;")
        button_layout.addWidget(debug_btn)
        
        button_layout.addStretch()
        
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.save_settings)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(save_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
    
    def show_debug_info(self):
        """Show debug information in a dialog"""
        try:
            # Get progress data
            data = get_progress_data()
            
            # Get debug details
            day_cutoff = mw.col.sched.dayCutoff
            day_start = day_cutoff - 86400  # Start of today
            
            done_query = f"""
                SELECT 
                    COUNT(*) as total_reviews,
                    SUM(CASE WHEN type = 0 THEN 1 ELSE 0 END) as new_reviews,
                    SUM(CASE WHEN type = 1 THEN 1 ELSE 0 END) as review_reviews,
                    SUM(CASE WHEN type IN (2, 3) THEN 1 ELSE 0 END) as learning_reviews
                FROM revlog
                WHERE id/1000 >= {day_start}
            """
            
            done_result = mw.col.db.first(done_query)
            total_revlog = mw.col.db.scalar("SELECT COUNT(*) FROM revlog")
            latest_entry = mw.col.db.first("SELECT id, id/1000, type, cid FROM revlog ORDER BY id DESC LIMIT 1")
            
            import time
            current_time = int(time.time())
            
            debug_text = f"""DEBUG INFORMATION:

=== TIMESTAMPS ===
dayCutoff (end of today): {day_cutoff}
day_start (start of today): {day_start}
Current time: {current_time}
Time since day started: {current_time - day_start} seconds ({(current_time - day_start)/3600:.1f} hours)

=== REVLOG QUERY ===
Query: {done_query}

Result: {done_result}
  - Total reviews: {done_result[0]}
  - New reviews: {done_result[1]}
  - Review reviews: {done_result[2]}
  - Learning reviews: {done_result[3]}
  
NOTE: This counts ALL reviews (button presses), not unique cards.
If you review the same card 3 times, it counts as 3.

=== REVLOG DATABASE ===
Total revlog entries: {total_revlog}
Latest entry: {latest_entry}
  - ID: {latest_entry[0] if latest_entry else 'None'}
  - Timestamp (seconds): {latest_entry[1] if latest_entry else 'None'}
  - Type: {latest_entry[2] if latest_entry else 'None'}
  - Card ID: {latest_entry[3] if latest_entry else 'None'}
  
Latest entry vs day_start: {latest_entry[1] - day_start if latest_entry else 'N/A'} seconds after day started

=== FINAL VALUES ===
data["done"]: {data["done"]}
data["remaining"]: {data["remaining"]}
data["new_done"]: {data["new_done"]}
data["review_done"]: {data["review_done"]}
data["learning_done"]: {data["learning_done"]}
"""
            
            # Show in a dialog with copyable text
            from aqt.qt import QTextEdit, QVBoxLayout, QDialog, QPushButton
            dialog = QDialog(self)
            dialog.setWindowTitle("Progress Bar Debug Info")
            dialog.setMinimumSize(600, 500)
            
            layout = QVBoxLayout()
            
            text_edit = QTextEdit()
            text_edit.setPlainText(debug_text)
            text_edit.setReadOnly(True)
            text_edit.setStyleSheet("font-family: monospace;")
            layout.addWidget(text_edit)
            
            close_btn = QPushButton("Close")
            close_btn.clicked.connect(dialog.accept)
            layout.addWidget(close_btn)
            
            dialog.setLayout(layout)
            dialog.exec()
            
        except Exception as e:
            showInfo(f"Error getting debug info: {str(e)}")
    
    def update_position_options(self):
        self.position_combo.clear()
        self.position_combo.addItems(["top-left", "top-right", "bottom-left", "bottom-right"])
        current_pos = self.config.get("position", "top-left")
        if current_pos in ["top-left", "top-right", "bottom-left", "bottom-right"]:
            self.position_combo.setCurrentText(current_pos)
        self.update_style_visibility()
    
    def update_style_visibility(self):
        is_bar = self.style_combo.currentText() == "box"
        self.bar_settings_widget.setVisible(is_bar)
        self.circle_settings_widget.setVisible(not is_bar)
    
    def choose_bar_color(self):
        from aqt.qt import QColor
        color = QColorDialog.getColor(QColor(self.bar_color), self)
        if color.isValid():
            self.bar_color = color.name()
            self.bar_color_btn.setStyleSheet(f"background-color: {self.bar_color}; min-width: 100px;")
    
    def choose_circle_color(self):
        from aqt.qt import QColor
        color = QColorDialog.getColor(QColor(self.circle_color), self)
        if color.isValid():
            self.circle_color = color.name()
            self.circle_color_btn.setStyleSheet(f"background-color: {self.circle_color}; min-width: 100px;")
    
    def choose_bg_color(self):
        from aqt.qt import QColor
        color = QColorDialog.getColor(QColor(self.bg_color), self)
        if color.isValid():
            self.bg_color = color.name()
            self.bg_color_btn.setStyleSheet(f"background-color: {self.bg_color}; min-width: 100px;")
    
    def choose_text_color(self):
        from aqt.qt import QColor
        color = QColorDialog.getColor(QColor(self.text_color), self)
        if color.isValid():
            self.text_color = color.name()
            self.text_color_btn.setStyleSheet(f"background-color: {self.text_color}; min-width: 100px;")
    
    def save_settings(self):
        """Save all settings"""
        display_style = self.style_combo.currentText()
        self.config["style"] = "bar" if display_style == "box" else display_style
        
        self.config["position"] = self.position_combo.currentText()
        self.config["bar_thickness"] = self.thickness_spin.value()
        self.config["bar_color"] = self.bar_color
        self.config["circle_size"] = self.size_spin.value()
        self.config["circle_color"] = self.circle_color
        self.config["bar_background"] = self.bg_color
        self.config["text_color"] = self.text_color
        self.config["show_percentage"] = self.show_percentage_check.isChecked()
        self.config["show_numbers"] = self.show_numbers_check.isChecked()
        self.config["show_new_count"] = self.show_new_check.isChecked()
        self.config["show_learning_count"] = self.show_learning_check.isChecked()
        self.config["show_review_count"] = self.show_review_check.isChecked()
        self.config["text_size"] = self.text_size_spin.value()
        self.config["gradient_type"] = self.gradient_combo.currentText()
        
        # Theme and glass
        self.config["theme"] = self.theme_combo.currentText()
        self.config["glass_effect"] = self.glass_effect_check.isChecked()
        self.config["glass_opacity"] = self.glass_opacity_spin.value() / 100.0
        self.config["glass_blur"] = self.glass_blur_spin.value()
        self.config["text_brightness"] = self.text_brightness_spin.value()
        
        # Debug output
        print(f"[Progress Bar] Saving settings:")
        print(f"  Glass Effect: {self.config['glass_effect']}")
        print(f"  Glass Opacity: {self.config['glass_opacity']}")
        print(f"  Glass Blur: {self.config['glass_blur']}")
        print(f"  Text Brightness: {self.config['text_brightness']}")
        print(f"  Theme: {self.config['theme']}")
        
        selected_decks = []
        for i in range(self.deck_list.count()):
            item = self.deck_list.item(i)
            if item.isSelected():
                selected_decks.append(item.text())
        self.config["selected_decks"] = selected_decks
        
        self.config["include_new_cards"] = self.include_new_check.isChecked()
        self.config["new_cards_mode"] = self.new_cards_mode_combo.currentData()
        self.config["new_cards_goal"] = self.new_cards_goal_spin.value()
        
        self.config["display_on_main"] = self.display_main_check.isChecked()
        self.config["display_on_home"] = self.display_home_check.isChecked()
        self.config["display_on_review"] = self.display_review_check.isChecked()
        
        save_config(self.config)
        self.accept()
        
        # Force immediate refresh of progress bar on all screens
        mw.reset()
        
        # If reviewing, also update the progress bar in the reviewer
        if mw.reviewer and mw.reviewer.card:
            try:
                # Remove old progress bar
                mw.reviewer.web.eval("""
                    var oldBox = document.getElementById('progress-stats-box');
                    var oldCircle = document.getElementById('progress-circle-container');
                    if (oldBox) oldBox.remove();
                    if (oldCircle) oldCircle.remove();
                """)
            except:
                pass
        
        showInfo("Settings saved! Progress bar updated.")

def show_settings():
    """Show settings dialog"""
    dialog = ProgressBarSettings(mw)
    dialog.exec()

def setup_menu():
    """Add menu item to Tools menu"""
    action = QAction("Progress Bar Settings...", mw)
    action.triggered.connect(show_settings)
    mw.form.menuTools.addAction(action)

# Register hooks
gui_hooks.webview_will_set_content.append(inject_progress_bar)
gui_hooks.reviewer_did_answer_card.append(on_reviewer_did_answer_card)
gui_hooks.webview_did_receive_js_message.append(handle_pycmd)

# Setup menu
setup_menu()
