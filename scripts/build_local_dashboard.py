"""Step 18 · Build the local, light-mode dashboard (dashboard/index.html) from dashboard/page.html.

Data: run `python scripts/pilot_dashboard_data.py dashboard/data` first to refresh the JSON files.
Serve: `python -m http.server 8050 -d dashboard`, then open http://localhost:8050
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "dashboard"

SHELL = """<!doctype html>
<html lang="en" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fresmart Pricing Studio</title>
<style>
:root {
  color-scheme: light;
  --font-anthropic-sans: "Inter", "Segoe UI", system-ui, -apple-system, Roboto, Arial, sans-serif;
  --font-anthropic-serif: Georgia, "Times New Roman", serif;
  --color-fg: #1d1c1a; --color-fg-muted: #6b6862; --color-bg: #f6f5f2; --color-panel: #ffffff;
  --color-border-line: #e6e3dd; --color-ok: #17804a; --color-warn: #a35a00; --color-bad: #c0352b;
  --cds-font-size-caption: 12.5px; --cds-font-size-body: 14px; --cds-font-size-heading: 16px; --cds-font-size-title: 26px;
  --cds-font-weight-medium: 500;
  --cds-gap-xs: 4px; --cds-gap-sm: 8px; --cds-gap-md: 16px; --cds-gap-lg: 22px; --cds-gap-xl: 32px;
  --cds-pad-xs: 4px; --cds-pad-sm: 8px; --cds-pad-md: 14px; --cds-pad-lg: 20px; --cds-pad-xl: 28px;
  --cds-radius: 8px;
  --cds-chart-axis: #d6d2ca; --cds-chart-grid: #ebe8e2; --cds-chart-reference: #a39e95; --cds-chart-muted: #b8b3aa;
  --cds-chart-status-critical: #d03b2f;
  --cds-surface-popover: #ffffff; --cds-border: #e2dfd8; --cds-text-secondary: #6b6862;
  --cds-shadow-popover: 0 10px 30px -8px rgba(20, 18, 14, .22), 0 2px 6px rgba(20, 18, 14, .06);
  --cds-dur-slow: 320ms; --cds-ease-out: cubic-bezier(.2, .8, .2, 1);
}
html, body { margin: 0; background: var(--color-bg); color: var(--color-fg); font-family: var(--font-anthropic-sans); -webkit-font-smoothing: antialiased; }
#dash-root { padding: var(--dash-gutter, 16px); min-height: 100vh; box-sizing: border-box; }
.dash-skeleton { color: transparent !important; border-radius: 6px; min-width: 3ch; display: inline-block;
  background: linear-gradient(90deg, #eeece8 25%, #f7f6f3 50%, #eeece8 75%); background-size: 200% 100%; animation: dash-sk 1.2s linear infinite; }
@keyframes dash-sk { to { background-position: -200% 0; } }
</style>
<script src="d3.min.js"></script>
<script src="dash-local.js"></script>
</head>
<body>
<div id="dash-root">
__PAGE__
</div>
</body>
</html>
"""

page = (ROOT / "page.html").read_text(encoding="utf-8")
(ROOT / "index.html").write_text(SHELL.replace("__PAGE__", page), encoding="utf-8")
print("built", ROOT / "index.html")
