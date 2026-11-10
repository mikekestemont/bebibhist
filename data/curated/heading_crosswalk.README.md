# Heading crosswalk

One row per printed heading path. `bhb categorise draft` refreshes the proposal columns. It does not change `approved_code`, `approved_theme`, `reviewer` or `note` once a cell has been filled, with one exception: a row the rule filled (`reviewer` = `rule`) takes the rule's deeper code when an unnumbered heading below the numbered one names a code of the scheme ("b. La vie économique / Les finances" is III.D.2.b.5.). To reconsider a row, clear those cells and run the draft again.

An empty `approved_code` means the row has not been reviewed.

- `approved_code`: a code from `scheme.csv`, or `BROAD` when the heading is too wide and each entry should be classified on its own.
- `approved_theme`: one of `reference`, `general`, `local`, `political`, `economic`, `social`, `religious`, `cultural`. Optional. Use it when no single code fits but the theme does.
- `reviewer`: your name. Rows filled by the number-and-label rule already have `reviewer` = `rule`.

`proposed_by` is `numbers+label` (the heading number and the wording agree, so the row is auto-approved), `numbers` (the number does not match the scheme wording; please review) or `classifier` (a suggestion from the titles under that heading). A classifier suggestion is used on the site only when `proposal_confidence` is at least 0.80.

Rows are sorted by `n_entries`, largest first.
