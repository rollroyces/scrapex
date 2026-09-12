"""Integration tests for Schema.heal — slow, network-dependent, or live-LLM tests.

These tests are NOT run by default unit-test invocation because they
may need:
- Real API keys (test_heal_live.py)
- A local fixture HTTP server (test_heal_real_websites.py)

Run them explicitly:
    pytest tests/integration/ -v
"""
