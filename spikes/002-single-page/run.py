"""Benchmark single-page extraction: scrapex vs alternatives.

Each library implements its own way of "fetch this URL and find these
fields". We time N iterations, report median + p95.

Libraries covered (no LLM, no browser):
  - scrapex (CSS strategy)
  - beautifulsoup4 + httpx
  - lxml + httpx

We do NOT compare against LLM-dependent tools (firecrawl, scrapegraphai,
crawl4ai-LLM) — those need API keys + cost tokens per call, not an
apples-to-apples comparison against a free CSS extractor.
"""
from __future__ import annotations

import statistics
import subprocess
import tempfile
from pathlib import Path


URL = "https://example.com"


RUNNERS: list[dict] = [
    {
        "name": "scrapex (CSS)",
        "deps": ["/Users/hermes/scrapex/dist/scrapex-0.1.0-py3-none-any.whl"],
        # Use a list of {time, name} dicts so the script self-reports.
        "script": """
import asyncio, time, statistics
import httpx
from scrapex import scrape, ScrapeRequest, Schema, FieldSpec, ExtractionStrategy

async def main():
    schema = Schema(
        strategy=ExtractionStrategy.CSS,
        fields=[
            FieldSpec(name="title", selector="h1"),
            FieldSpec(name="paragraph", selector="p"),
        ],
    )
    times = []
    for _ in range(10):
        t0 = time.perf_counter()
        await scrape(ScrapeRequest(url=__URL__, schema=schema))
        times.append(time.perf_counter() - t0)
    print("MEDIAN={:.4f}".format(statistics.median(times)))
    print("P95={:.4f}".format(sorted(times)[-1]))

asyncio.run(main())
""".replace("__URL__", repr(URL)),
    },
    {
        "name": "beautifulsoup4 + lxml + httpx",
        "deps": ["beautifulsoup4", "lxml", "httpx"],
        "script": """
import time, statistics
import httpx
from bs4 import BeautifulSoup

times = []
for _ in range(10):
    t0 = time.perf_counter()
    r = httpx.get(__URL__, follow_redirects=True)
    soup = BeautifulSoup(r.text, "lxml")
    title = soup.select_one("h1")
    para = soup.select_one("p")
    times.append(time.perf_counter() - t0)
print("MEDIAN={:.4f}".format(statistics.median(times)))
print("P95={:.4f}".format(sorted(times)[-1]))
""".replace("__URL__", repr(URL)),
    },
    {
        "name": "lxml + httpx",
        "deps": ["lxml", "httpx"],
        "script": """
import time, statistics
import httpx
from lxml import html

times = []
for _ in range(10):
    t0 = time.perf_counter()
    r = httpx.get(__URL__, follow_redirects=True)
    tree = html.fromstring(r.text)
    title = tree.xpath("//h1/text()")
    para = tree.xpath("//p/text()")
    times.append(time.perf_counter() - t0)
print("MEDIAN={:.4f}".format(statistics.median(times)))
print("P95={:.4f}".format(sorted(times)[-1]))
""".replace("__URL__", repr(URL)),
    },
]


def run_runner(label: str, deps: list[str], script: str) -> dict | None:
    """Create a fresh venv, install deps, run the script."""
    venv_dir = Path(tempfile.mkdtemp(prefix="bench_")) / "venv"
    try:
        subprocess.run(["uv", "venv", str(venv_dir)], check=True, capture_output=True)
        python = str(venv_dir / "bin" / "python")
        # Install deps
        install = subprocess.run(
            ["uv", "pip", "install", "--python", python, "--quiet", *deps],
            capture_output=True,
            text=True,
        )
        if install.returncode != 0:
            print(f"  {label}: install failed — {install.stderr[-300:]}")
            return None
        # Write and run
        script_path = venv_dir / "bench.py"
        script_path.write_text(script)
        res = subprocess.run(
            [python, str(script_path)],
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            print(f"  {label}: run failed — {res.stderr[-300:]}")
            return None
        out = res.stdout
        median_s = None
        p95_s = None
        for line in out.splitlines():
            if line.startswith("MEDIAN="):
                median_s = float(line.split("=", 1)[1])
            elif line.startswith("P95="):
                p95_s = float(line.split("=", 1)[1])
        if median_s is None or p95_s is None:
            print(f"  {label}: no MEDIAN/P95 in output: {out!r}")
            return None
        return {
            "library": label,
            "median_seconds": median_s,
            "p95_seconds": p95_s,
        }
    finally:
        subprocess.run(["rm", "-rf", str(venv_dir)], capture_output=True)


def main() -> None:
    print(f"Benchmarking single-page extraction on {URL}\n")
    results: list[dict] = []
    for r in RUNNERS:
        print(f"→ {r['name']}...", end=" ", flush=True)
        result = run_runner(r["name"], r["deps"], r["script"])
        if result:
            results.append(result)
            print(
                f"median={result['median_seconds']:.3f}s  p95={result['p95_seconds']:.3f}s"
            )
        else:
            print("FAILED")

    if not results:
        print("\nNo successful runs.")
        return

    print("\n=== RESULTS (median over 10 runs) ===")
    print(f"{'Library':<35} {'Median':>10} {'p95':>10}")
    print("-" * 55)
    for r in sorted(results, key=lambda x: x["median_seconds"]):
        print(f"{r['library']:<35} {r['median_seconds']:>9.3f}s {r['p95_seconds']:>9.3f}s")

    fastest = min(results, key=lambda x: x["median_seconds"])
    print(f"\nFastest: {fastest['library']} ({fastest['median_seconds']:.3f}s)")
    for r in results:
        if r is not fastest:
            ratio = r["median_seconds"] / fastest["median_seconds"]
            print(f"  {r['library']} is {ratio:.1f}x slower")


if __name__ == "__main__":
    main()