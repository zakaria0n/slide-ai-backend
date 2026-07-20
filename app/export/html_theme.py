"""Theme palettes for exports.

Mirrors the frontend design system (Phase 11) so exported HTML/PPTX match
the in-app deck. Kept server-side and dependency-free (plain dicts) so the
export engine has no React dependency.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ThemeTokens:
    bg: str
    surface: str
    surface2: str
    border: str
    text: str
    text_muted: str
    text_dim: str
    accent: str
    accent2: str
    accent3: str
    font_heading: str
    font_body: str
    radius: str
    radius_lg: str
    gradient: str


# 15 themes, keyed identically to the frontend (Phase 11).
_THEMES: dict[str, ThemeTokens] = {
    "modern": ThemeTokens("#0b0b16", "rgba(255,255,255,0.04)", "rgba(255,255,255,0.07)", "rgba(255,255,255,0.12)", "#f4f4ff", "#a0a0c0", "#6b6b8a", "#7c6aff", "#ff6ac1", "#37e0c8", "'Syne', sans-serif", "'DM Sans', sans-serif", "14px", "24px", "linear-gradient(135deg, #7c6aff, #ff6ac1)"),
    "corporate": ThemeTokens("#0f172a", "rgba(255,255,255,0.05)", "rgba(255,255,255,0.08)", "rgba(148,163,184,0.25)", "#e8edf5", "#94a3b8", "#64748b", "#2563eb", "#0ea5e9", "#38bdf8", "'Space Grotesk', sans-serif", "'DM Sans', sans-serif", "10px", "18px", "linear-gradient(135deg, #2563eb, #0ea5e9)"),
    "startup": ThemeTokens("#0c0a14", "rgba(255,255,255,0.05)", "rgba(255,255,255,0.09)", "rgba(255,255,255,0.12)", "#fdfdfd", "#b6b6cf", "#7c7c98", "#ff7a45", "#ffd23f", "#22d3a6", "'Syne', sans-serif", "'DM Sans', sans-serif", "16px", "28px", "linear-gradient(135deg, #ff7a45, #ffd23f)"),
    "education": ThemeTokens("#102a2e", "rgba(255,255,255,0.06)", "rgba(255,255,255,0.10)", "rgba(255,255,255,0.16)", "#f3fbf6", "#9fd3c0", "#6fa893", "#16a34a", "#22c55e", "#f59e0b", "'Space Grotesk', sans-serif", "'DM Sans', sans-serif", "14px", "22px", "linear-gradient(135deg, #16a34a, #22c55e)"),
    "medical": ThemeTokens("#0a1f2e", "rgba(255,255,255,0.05)", "rgba(255,255,255,0.08)", "rgba(125,211,252,0.22)", "#eaf6ff", "#9ec5e0", "#6a94ad", "#0ea5e9", "#14b8a6", "#38bdf8", "'Space Grotesk', sans-serif", "'DM Sans', sans-serif", "12px", "20px", "linear-gradient(135deg, #0ea5e9, #14b8a6)"),
    "finance": ThemeTokens("#0b1220", "rgba(255,255,255,0.04)", "rgba(255,255,255,0.07)", "rgba(212,175,55,0.22)", "#f5f7fa", "#a7b0bd", "#6b7280", "#1e7d5a", "#d4af37", "#34d399", "'Lora', serif", "'DM Sans', sans-serif", "10px", "16px", "linear-gradient(135deg, #1e7d5a, #d4af37)"),
    "luxury": ThemeTokens("#14110d", "rgba(255,255,255,0.04)", "rgba(255,255,255,0.06)", "rgba(201,162,92,0.30)", "#f6efdf", "#c2b48f", "#8a7c5c", "#c9a25c", "#e8c98a", "#d4af37", "'Lora', serif", "'DM Sans', sans-serif", "8px", "14px", "linear-gradient(135deg, #c9a25c, #e8c98a)"),
    "minimal": ThemeTokens("#ffffff", "rgba(0,0,0,0.03)", "rgba(0,0,0,0.05)", "rgba(0,0,0,0.10)", "#111111", "#555555", "#999999", "#111111", "#666666", "#2563eb", "'Space Grotesk', sans-serif", "'DM Sans', sans-serif", "10px", "18px", "linear-gradient(135deg, #111111, #666666)"),
    "glass": ThemeTokens("rgba(15,18,40,0.6)", "rgba(255,255,255,0.08)", "rgba(255,255,255,0.12)", "rgba(255,255,255,0.18)", "#f4f5ff", "#b9bce0", "#8083a8", "#9b7bff", "#57e6ff", "#ff8fd6", "'Syne', sans-serif", "'DM Sans', sans-serif", "18px", "28px", "linear-gradient(135deg, #9b7bff, #57e6ff)"),
    "dark": ThemeTokens("#000000", "rgba(255,255,255,0.05)", "rgba(255,255,255,0.09)", "rgba(255,255,255,0.14)", "#ffffff", "#a1a1aa", "#52525b", "#ffffff", "#a1a1aa", "#3b82f6", "'Space Grotesk', sans-serif", "'DM Sans', sans-serif", "12px", "20px", "linear-gradient(135deg, #ffffff, #a1a1aa)"),
    "neon": ThemeTokens("#06000f", "rgba(255,255,255,0.04)", "rgba(255,255,255,0.07)", "rgba(255,0,200,0.30)", "#f0e9ff", "#b78bff", "#7c5cae", "#ff00c8", "#00f0ff", "#aaff00", "'Syne', sans-serif", "'DM Sans', sans-serif", "12px", "22px", "linear-gradient(135deg, #ff00c8, #00f0ff)"),
    "apple": ThemeTokens("#fbfbfd", "rgba(0,0,0,0.03)", "rgba(0,0,0,0.05)", "rgba(0,0,0,0.10)", "#1d1d1f", "#6e6e73", "#a1a1a6", "#0071e3", "#42a5f5", "#34c759", "'SF Pro Display', sans-serif", "'SF Pro Display', sans-serif", "14px", "22px", "linear-gradient(135deg, #0071e3, #42a5f5)"),
    "google": ThemeTokens("#ffffff", "rgba(0,0,0,0.03)", "rgba(0,0,0,0.05)", "rgba(0,0,0,0.10)", "#202124", "#5f6368", "#9aa0a6", "#4285f4", "#ea4335", "#34a853", "'Product Sans', sans-serif", "'Product Sans', sans-serif", "12px", "20px", "linear-gradient(135deg, #4285f4, #ea4335)"),
    "microsoft": ThemeTokens("#f3f2f1", "rgba(0,0,0,0.03)", "rgba(0,0,0,0.05)", "rgba(0,0,0,0.12)", "#201f1e", "#605e5c", "#8a8886", "#0078d4", "#d83b01", "#107c10", "'Segoe UI', sans-serif", "'Segoe UI', sans-serif", "8px", "14px", "linear-gradient(135deg, #0078d4, #d83b01)"),
    "openai": ThemeTokens("#0d0d0d", "rgba(255,255,255,0.04)", "rgba(255,255,255,0.07)", "rgba(255,255,255,0.12)", "#ececf1", "#9b9ba6", "#6b6b76", "#10a37f", "#1fb890", "#19c37d", "'Space Grotesk', sans-serif", "'DM Sans', sans-serif", "12px", "20px", "linear-gradient(135deg, #10a37f, #1fb890)"),
}


def tokens_for(theme_name: str | None) -> ThemeTokens:
    if theme_name and theme_name in _THEMES:
        return _THEMES[theme_name]
    return _THEMES["modern"]
