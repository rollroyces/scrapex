"""Measure the actual token savings from the optimization.

Runs the new cleaning + slim prompt on representative HTML and reports:
- Old prompt tokens
- New prompt tokens
- Old cleaned HTML tokens (naive truncate at 50K)
- New cleaned HTML tokens (clean_html_for_llm at 30K)
- Total cost per call

Run with: python spikes/005-llm-schema/measure.py
"""
from __future__ import annotations

import tiktoken

from scrapex.html_clean import clean_html_for_llm, estimate_tokens

# A representative "messy real-world" HTML page
SAMPLE = """
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Some News Site</title>
    <link rel="stylesheet" href="main.css">
    <script src="jquery.js"></script>
    <script src="analytics.js"></script>
    <script>
        window.dataLayer = [];
        function gtag() { dataLayer.push(arguments); }
        gtag('js', new Date());
        gtag('config', 'GA-XXXX');
    </script>
    <style>
        body { font-family: sans-serif; }
        .article { margin-bottom: 20px; }
    </style>
    <!-- This comment should be stripped -->
    <!-- Multiple comments for noise -->
</head>
<body>
    <nav>
        <a href="/">Home</a> |
        <a href="/about">About</a> |
        <a href="/contact">Contact</a>
    </nav>

    <header>
        <h1>Daily News</h1>
        <p>Your source for everything</p>
    </header>

    <aside>
        <h3>Trending</h3>
        <ul><li>Story 1</li><li>Story 2</li></ul>
    </aside>

    <main>
        <article>
            <h2>Big Story of the Day</h2>
            <p>Lorem ipsum dolor sit amet, consectetur adipiscing elit. ...
            ... lots of paragraphs ...</p>
        </article>
        <article>
            <h2>Second Story</h2>
            <p>More content...</p>
        </article>
    </main>

    <footer>
        <p>Copyright 2026, Some News Inc.</p>
        <p>Privacy Policy | Terms</p>
    </footer>

    <script>
        // more analytics
        console.log('page loaded');
    </script>
</body>
</html>
"""

NEW_PROMPT = """\
You are a schema synthesizer. Return one JSON object.

Schema:
{{"fields": [{{"name": str, "selector": str, "attr": "text"|"href", "reason": str}}]}}

Rules:
- One field per piece of data the user asked for.
- CSS selectors only. Prefer class-targeted over positional.
- "text" for visible text, "href" for links.
- "reason" explains selector choice for the maintainer.

Goal: {goal}

HTML:
{html}

Output ONLY the JSON."""


OLD_PROMPT = """\
You are a precise web-scraping schema synthesizer.

Given an HTML page and a one-line goal, return a JSON object with a single
"fields" key. Each entry in "fields" describes one piece of data to extract:

  {{
    "name": "snake_case_field_name",
    "selector": "CSS selector that targets the element (text default)",
    "attr": "text" or "href" — which attribute to read
    "reason": "one sentence explaining why you picked this selector"
  }}

Rules:
- One field per piece of data the user asked for. Do NOT hallucinate extras.
- Selectors must be CSS (not XPath). Prefer class-targeted selectors
  over positional ones.
- Use "text" for visible text, "href" for links.
- The "reason" is for the human who will maintain this — be specific.

Goal: {goal}

HTML:
{html}

Output ONLY the JSON object. No prose, no markdown fences."""


def measure(label: str, prompt: str, html: str) -> tuple[int, int, int]:
    """Returns (template_tokens, html_tokens, total_tokens)."""
    enc = tiktoken.encoding_for_model("gpt-4o-mini")
    template_tokens = len(enc.encode(prompt.split("HTML:")[0] + "HTML:\n"))
    html_tokens = len(enc.encode(html))
    total = template_tokens + html_tokens
    print(f"{label}:")
    print(f"  template: {template_tokens} tokens")
    print(f"  html:     {html_tokens} tokens")
    print(f"  total:    {total} tokens")
    return template_tokens, html_tokens, total


# Scale the sample to a "real page" — repeat the article block
big_html = SAMPLE * 5
print("=" * 70)
print(f"Sample page size: {len(big_html)} chars, ~{estimate_tokens(big_html)} tokens raw")
print("=" * 70)

# Old approach: send raw HTML truncated at 50K chars
old_html = big_html[:50_000]
old_prompt = OLD_PROMPT.format(goal="the article titles", html=old_html)
old_p, old_h, old_total = measure("OLD (verbose prompt + raw 50K)", old_prompt, old_html)

# New approach: clean HTML, slim prompt
new_html = clean_html_for_llm(big_html)
new_prompt = NEW_PROMPT.format(goal="the article titles", html=new_html)
new_p, new_h, new_total = measure("NEW (slim prompt + cleaned 30K)", new_prompt, new_html)

print("=" * 70)
savings = old_total - new_total
pct = savings / old_total * 100
print(f"SAVINGS: {savings} tokens per call ({pct:.0f}%)")
print(f"=" * 70)

# At gpt-4o-mini pricing ($0.15 / 1M input tokens):
cost_per_call = savings * 0.15 / 1_000_000
print(f"Cost savings: ${cost_per_call:.6f} per call (at gpt-4o-mini pricing)")
print()
print("Verdict:")
print(f"  prompt overhead: {old_p} → {new_p} ({old_p - new_p} tokens saved)")
print(f"  HTML payload:    {old_h} → {new_h} ({old_h - new_h} tokens saved)")
print(f"  total:           {old_total} → {new_total} ({savings} tokens saved, {pct:.0f}%)")