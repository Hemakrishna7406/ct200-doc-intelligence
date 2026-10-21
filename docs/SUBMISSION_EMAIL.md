# Submission email (draft)

Deliverable #4 from the assignment brief. Copy, fill the bracketed fields, send.

---

**To:** [recruiter / hiring contact]
**Cc:** —
**Subject:** AI Engineering Internship — Technical Assignment Submission — [Your Name]

Dear [Name],

Thank you for the opportunity to attempt the Tri9T AI / AffineSurge AI
Engineering Internship technical assignment. Please find my submission below.

**GitHub repository:** [repo URL]
**Approach document:** [repo URL]/blob/main/docs/APPROACH.md

**What I built**

A FastAPI backend that parses the CardioTrack CT-200 manual (PDF) into a
versioned, hierarchical tree, lets a user build version-pinned selections,
generates QA test-case ideas from those selections via an LLM, and detects when
a previously generated test case has gone stale after the document is
re-ingested.

**How to run it** (details in the README):

```
pip install -r requirements.txt
uvicorn app.main:app --reload      # docs at /docs
pytest                             # 27 tests
python scripts/e2e_demo.py         # full v1 -> v2 -> staleness flow
```

No API key is required — the default provider is an offline, deterministic mock
so the whole pipeline runs end-to-end; swapping `CT200_LLM_PROVIDER` to a real
provider uses the identical validation/retry path.

**Highlights I'd point to**

* Level is derived from the section number's depth, not font size — which is what
  keeps `3.2` (bold, body-sized) and the level-4 `2.1.1.1` correctly placed.
* Duplicate headings (`Error Codes` at 4.2 and 7.1) become two distinct nodes
  with correct parents; out-of-order sections (3.4 before 3.3) are reordered;
  the skipped level in `2.1.1.1` is re-attached and flagged rather than silently
  renumbered.
* Change detection and generation operate on a node's *subtree*, so a container
  whose table changed (4.2's error table) is correctly flagged as changed.
* Structured-output validation with a repair-retry, and a documented failure
  mode that stores malformed responses instead of dropping them.
* A decision log covering the three questions, including where I chose
  simplicity over correctness.

I'm happy to walk through any part of the code and make a live change during the
interview.

Thank you for your time.

Best regards,
[Your Name]
[Phone] · [Email] · [GitHub profile]
