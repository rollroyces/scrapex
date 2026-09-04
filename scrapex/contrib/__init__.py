"""Opt-in community-contributed helpers.

This package contains features that:
- require a non-default opt-in (the user has to install the ``[contrib]`` extra)
- are useful for a specific use case but not part of scrapex's core
- are explicitly named to make the "this is community-grade, audit
  before using" contract obvious

If you find yourself reaching for a contrib module in production, read
its source first.
"""

from __future__ import annotations

from scrapex.contrib import captcha, sessions

__all__ = ["captcha", "sessions"]
