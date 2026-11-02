# Language: hand-checked answer keys

Both files check `language_suggested` (`bhb language apply`, see `pipeline/bhb/language.py`). Labelled by Claude
on 2 November 2026 from the title and, where the title alone does not tell, the journal or volume it appears in.

| File | Contents |
|---|---|
| `sample.csv` | 40 entries per decade of the BGB volume (`bhb language sample`, seed 7), labelled without seeing the suggestions. `checked` holds ISO 639-1 codes separated by `|` in the order the title gives them, or `?` when nothing tells. Score with `bhb language score`. |
| `review.csv` | 30 entries flagged bilingual and 30 suggested in a language other than Dutch, French, English or German, with the suggestion at the time (`suggested`), the right answer (`checked`) and a note where they differ. |

A bracketed French translation by the bibliography's editors does not make an entry bilingual; a title printed in
two languages, or a parallel title in the State Archives' catalogue, does.
