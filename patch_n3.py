"""Canvas guidance batch — run then delete."""
import io


def read(p):
    with io.open(p, encoding="utf-8") as f:
        return f.read()


def write(p, s):
    with io.open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(s)


# ── 1. SKILL.md: canvas debugging guidance ──
p = "app/api/routes/skill.py"
s = read(p)
old = """## Common mistakes to avoid"""
new = """## CANVAS SLIDES — DO IT RIGHT (free models get this wrong)

When drawing with <canvas>:
- Grab it ONCE: `var cv = document.querySelector("canvas");` — never
  `getElementsByTagName("canvas")` (that returns a LIST, `.getContext` on it
  throws). Check `if (!cv) return;` before drawing.
- Your code runs at the END of <body>: the DOM is ready, no DOMContentLoaded
  wrapper needed.
- NO external fonts or images inside the sandbox (CSP): use the theme CSS
  variables and system fonts; images must be inline data: URIs.
- Wrap risky drawing in try/catch so one failure never blanks the slide.
- For flowcharts/architecture: animate connectors with stroke-dashoffset and
  pop nodes in sequence (see DIAGRAMS above). For algorithms: step captions +
  data visualization (see ALGORITHMS above).

## Common mistakes to avoid"""
assert old in s, "skill canvas"
s = s.replace(old, new)
write(p, s)
print("skill canvas guidance added")

# ── 2. spec_provider rule 10: canvas guidance ──
p = "app/generation/spec_provider.py"
s = read(p)
old = """   - HARD RULES (sandbox enforces them anyway): no external network requests
     (no CDN/fetch/img URLs), no localStorage/cookies, no access to parent.
     Everything self-contained in your html/css/js strings."""
new = """   - CANVAS: query it ONCE with document.querySelector("canvas") — never
     getElementsByTagName("canvas") (a list has no .getContext). Null-check
     before drawing. No external fonts (CSP): use system fonts / var(--font-*).
     Everything self-contained in your html/css/js strings."""
assert old in s, "rule 10 canvas"
s = s.replace(old, new)
write(p, s)
print("spec_provider canvas guidance added")

# ── 3. custom slide tool description: canvas note ──
p = "app/mcp/tools.py"
s = read(p)
needle = "always ending settled and fully visible. No external network requests, no localStorage, no parent access. Omitted fields keep their current code."
replacement = (
    "always ending settled and fully visible. CANVAS: query once with "
    "document.querySelector(\"canvas\") (never getElementsByTagName — a list "
    "has no .getContext) and null-check before drawing. No external "
    "network/fonts (CSP) — use system fonts and inline data: URIs. Omitted "
    "fields keep their current code."
)
assert needle in s, "tool desc canvas"
s = s.replace(needle, replacement, 1)
write(p, s)
print("mcp tool desc patched")
