# journals.csv and journal_spellings.csv

Written by `bhb journals apply` (`pipeline/bhb/journals.py`); see `docs/JOURNAL_PROPOSAL.md`. **Machine-built, not
reviewed.** A review, from the largest journals down, is planned for later.

`journals.csv`: one row per journal. `id` is `issn:<ISSN>` when an ISSN is known (from the Crossref and VABB-SHW
matches), otherwise `t:<folded title>`; `title` is the most frequent spelling written out in full; `issn` lists the
print and online numbers; `spellings` and `articles` count what the map assigns to it.

`journal_spellings.csv`: a folded spelling of a journal name as printed → its journal, with the rule that linked it:
`issn` (its articles matched one ISSN), `full` (a frequent spelling written out in full), `variant` (a full title plus
a place, subtitle or volume) or `abbreviation` (its words begin the words of exactly one full title, in order).
Spellings that no rule links are not listed; their articles keep the journal name as printed.
