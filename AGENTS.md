# Instructions for coding agents

The current task is **`docs/IMPLEMENTATION_PLAN.md`** (phase 2); where it conflicts with older documents, it wins. For background, start with **`docs/PROTOTYPE_SPEC.md`**: it is the self-contained brief (context, data formats, record model,
steps, website requirements, definition of done). `pipeline/README.md` documents the pipeline. The internal project
plan and notes are in `../bebibhist-raw/notes/` (private; not every contributor has them).

Ground rules:
- Raw inputs live in `../bebibhist-raw` (or the folder named by `BHB_RAW`) and are read-only: `2023-12-29/`, `exports Rijksarchief/`, `data/raw/`, `data/interim/`, `legacy/`.
- This repository is public. Internal notes (people, terms of work, assessments, budget, governance, correspondence, to-do lists) go to `../bebibhist-raw/notes/`, never here.
- Never commit large data (PDFs, SQLite, CSV > 20 MB); see `.gitignore`.
- Python code lives in the `bhb` package (`pipeline/`), with pytest tests; no notebooks.
- No LLM API calls (decision of 11 Oct 2026). Local open models are allowed.
- Record decisions you take on your own in `docs/DECISIONS.md` (one line each, with rationale).
- Keep the printed citation text intact; flag machine-derived values.
- The data are CC BY-NC 4.0 (https://creativecommons.org/licenses/by-nc/4.0/). The code stays MIT.
