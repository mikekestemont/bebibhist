# Answer key for the citation pass

`key.csv`: 150 printed entries drawn at random, 25 per decade (1950s–2000s, the 2000s with 2008), for judging the
parser and the LLM citation pass (`bhb citations key`, `docs/IMPLEMENTATION_PLAN.md` §5c). Unlike the DOI key, it
does not depend on the parser: an entry is in it whether the parser got it right or not.

Each entry was drafted from the parser's fields and every field was then checked against the printed citation by
an AI assistant (Claude, 3 Nov 2026; `checked_by` = `claude`). No person has reviewed it yet; corrections are welcome.

Columns: `split` (`dev` for tuning prompts, `test` for the final comparison only), `type`, `authors` and `editors`
(family names, `; `), `title` (title and subtitle as printed), `title_translated` (the editors' bracketed
translation; a bracketed gloss such as "[famille luxembourgeoise]" is not one), `host` (journal or volume, as
printed), `volume`, `issue`, `pages`, `year`, `place`, `publisher`, `extent`, `series`, `series_number`, and the
`printed` citation.

Conventions: `a || b` accepts either value (an empty alternative accepts no value); `book|article` accepts either
type; `*` means the printed text does not settle the field, and it is not scored. Printed spellings and OCR errors
are kept as printed ("brabanlse"), except where a value is plainly broken ("pp. 3953" is pages 39–53). Persons are
those of the entry itself; the editors of a chapter's volume belong to the volume.
