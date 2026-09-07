# Spike 006 — HK SRPE workflow with browser-use

## Honest context first

The user described a multi-step workflow against the Hong Kong
Sales of First-hand Residential Properties Electronic Platform (SRPE):

  1. Load the disclaimer page
  2. Check the T&C checkbox + click Continue
  3. Filter "items updated within last 7 days"
  4. For each of ~98 updated items:
     a. Click into the item's detail page
     b. Find "register of transactions" link
     c. Download the PDF
  5. Persist state across 98 page visits

The user wants this to require "less maintenance" — they want to send
a natural-language instruction to an LLM and have the agent figure
out the workflow.

This is **an agent loop**, not a single-page extraction. scrapex is
explicitly single-page. The right tool for this is **browser-use** —
112k GitHub stars, MIT, built for "natural-language instruction +
LLM figures out the clicks" workflows.

## What we're testing

Does browser-use actually solve this specific HK government workflow
end-to-end? Specifically:

1. Can it handle the T&C checkbox + Continue button?
2. Can it filter by date?
3. Can it iterate 98 items without state corruption?
4. Can it find the right PDF link on each detail page?
5. Can it handle download links?

If yes to all: ship a thin wrapper around browser-use specifically
for HK government real-estate sites. ~30 lines of glue.

If no on any: document the failure mode and recommend alternatives.

## Out of scope (already rejected)

- Building this on top of scrapex. Would invert scrapex's contract.
- Building a general agent framework. browser-use already exists.
- Adding PDF parsing. That's a separate problem.

## Honest concerns before running

1. **T&C pages often have anti-bot defenses.** "I have read and
   understood" + checkbox is a classic bot-detection pattern. browser-use
   uses OpenAI's operator model under the hood; it might be flagged.
2. **Government sites are notoriously fragile.** They change without
   notice. Whatever we build needs to be replaceable in <1 day.
3. **PDF download links may require JS-driven navigation** that
   bypasses HTTP cookies. browser-use should handle this; pure HTTP
   scrapers (like scrapex) cannot.
4. **No API key.** browser-use's default model is OpenAI's. We have
   no key set in this env. This probe will **fail at the LLM call**
   unless the user provides one. Same blocker as spike 005.