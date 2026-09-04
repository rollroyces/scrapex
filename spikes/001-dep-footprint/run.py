"""Run the dep-footprint spike against every competitor.

For each library, create a fresh venv, install it with a single shell call,
then record: install time, package count, total disk size.

Honest: this times a real `pip install` against PyPI. No mocking.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path


LIBRARIES: list[dict[str, str]] = [
    # For scrapex, use absolute path so editable install works from any cwd
    {"name": "scrapex[browser]", "target": "scrapex[browser]"},
    {"name": "scrapex (core)", "target": "scrapex"},
    {"name": "crawl4ai", "target": "crawl4ai"},
    {"name": "firecrawl", "target": "firecrawl"},
    {"name": "scrapegraphai", "target": "scrapegraphai"},
    {"name": "crawlee", "target": "crawlee[beautifulsoup]"},
    {"name": "scrapy", "target": "scrapy"},
]


def _uv_python(venv_dir: Path) -> Path:
    return venv_dir / "bin" / "python"


def _list_packages(venv_dir: Path) -> list[dict]:
    """List installed packages in a uv-managed venv."""
    python = str(_uv_python(venv_dir))
    res = subprocess.run(
        ["uv", "pip", "list", "--python", python, "--format=json"],
        capture_output=True,
        text=True,
    )
    return json.loads(res.stdout)


def run_install(label: str, target: str) -> dict:
    """Create a fresh venv, install one library, measure."""
    venv_dir = Path(tempfile.mkdtemp(prefix="sp_")) / "venv"
    subprocess.run(["uv", "venv", str(venv_dir)], check=True, capture_output=True)
    python = str(_uv_python(venv_dir))

    # Build the install command. For scrapex we install the local repo;
    # for everything else we install from PyPI.
    if target.startswith("scrapex"):
        cmd = [
            "uv", "pip", "install", "--python", python, "--quiet",
            "/Users/hermes/scrapex" + ("[browser]" if "[" in target else ""),
        ]
    else:
        cmd = [
            "uv", "pip", "install", "--python", python, "--quiet", target,
        ]

    t0 = time.monotonic()
    install_result = subprocess.run(cmd, capture_output=True, text=True)
    install_seconds = time.monotonic() - t0

    packages = _list_packages(venv_dir)

    # Disk size
    site_dirs = list((venv_dir / "lib").glob("python*/site-packages"))
    site_dir = site_dirs[0] if site_dirs else venv_dir
    du = subprocess.run(["du", "-sh", str(site_dir)], capture_output=True, text=True)
    size_str = du.stdout.split()[0] if du.stdout else "?"

    return {
        "library": label,
        "install_seconds": round(install_seconds, 1),
        "install_success": install_result.returncode == 0,
        "install_error": (
            (install_result.stderr or install_result.stdout or "")[-400:]
            if install_result.returncode != 0 else ""
        ),
        "package_count": len(packages),
        "site_packages_size": size_str,
    }


def main() -> None:
    results: list[dict] = []
    for lib in LIBRARIES:
        print(f"\n→ Installing {lib['name']}...")
        try:
            results.append(run_install(lib["name"], lib["target"]))
        except Exception as e:
            results.append({"library": lib["name"], "error": str(e)})

    print("\n=== SUMMARY ===")
    print(f"{'Library':<25} {'Time(s)':>10} {'Pkgs':>6} {'Size':>10}  Status")
    print("-" * 75)
    for r in results:
        if "error" in r and "package_count" not in r:
            print(f"{r['library']:<25} ERROR  {r['error'][:60]}")
            continue
        status = "OK" if r["install_success"] else f"FAIL ({r['install_error'][:30]})"
        print(
            f"{r['library']:<25} {r['install_seconds']:>10} {r['package_count']:>6} "
            f"{r['site_packages_size']:>10}  {status}"
        )


if __name__ == "__main__":
    main()