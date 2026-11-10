# Instructions for coding agents

The current task is **`docs/IMPLEMENTATION_PLAN.md`** (phase 2); where it conflicts with older documents, it wins.
Phase 3, maintenance from master files, is proposed in `docs/MAINTENANCE_PLAN.md` and not started. For background, start with **`docs/PROTOTYPE_SPEC.md`**: it is the self-contained brief (context, data formats, record model,
steps, website requirements, definition of done). `pipeline/README.md` documents the pipeline. The internal project
plan and notes are in `../bebibhist-raw/notes/` (private; not every contributor has them).

Ground rules:
- Raw inputs live in `../bebibhist-raw` (or the folder named by `BHB_RAW`) and are read-only: `2023-12-29/`, `exports Rijksarchief/`, `data/raw/`, `data/interim/`, `legacy/`.
- This repository is public. Internal notes (people, terms of work, assessments, budget, governance, correspondence, to-do lists) go to `../bebibhist-raw/notes/`, never here.
- Never commit large data (PDFs, SQLite, CSV > 20 MB); see `.gitignore`.
- Python code lives in the `bhb` package (`pipeline/`), with pytest tests; no notebooks.
- LLM API calls only for the citation clean-up pass and, since 9 Nov 2026, for proposing codes of the classification
  for the printed headings of 1952–1992 (`bhb categorise propose`), through OpenRouter (decision of 31 Oct 2026, replacing the ban
  of 11 Oct): any provider at full or fp8 precision (training on the open data is allowed, 3 Nov 2026), pinned model versions, every answer cached, the
  key in `OPENROUTER_API_KEY` and never in the repository; entries already right, or matched to a DOI or VABB
  record, are not sent for clean-up, but their titles are sent, title only, for the translations into Dutch, French
  and English (decision of 2 Nov 2026; plan §5c). Local open models are allowed for everything else.
- Record decisions you take on your own in `docs/DECISIONS.md` (one line each, with rationale).
- Keep the printed citation text intact; flag machine-derived values.
- The data are CC BY-NC-SA 4.0 (https://creativecommons.org/licenses/by-nc-sa/4.0/). The code stays MIT.
