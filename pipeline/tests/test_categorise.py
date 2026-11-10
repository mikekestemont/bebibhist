from bhb.categorise import (
    categories_for,
    choose_tau_theme,
    heading_key,
    refresh_crosswalk,
)
from bhb.model import Record
from bhb.categorise import Scored


def _record(**kwargs) -> Record:
    base = dict(id="bhb:1990-1", source="print-straive", bgb_year=1990, role="entry")
    base.update(kwargs)
    return Record(**base)


def test_heading_key_ignores_spaces_date_ranges_and_the_dutch_half():
    spaced = heading_key(["C. Lim bourg (1) — Limburg"])
    tight = heading_key(["C. Limbourg — Limburg"])
    assert spaced == tight
    early = heading_key(["F. De 1789 à nos jours, 1789-1970"])
    late = heading_key(["F. De 1789 à nos jours, 1789–1972"])
    assert early == late
    assert early != heading_key(["F. De 1830 à nos jours, 1830-1914"])


def test_draft_keeps_a_reviewers_cells():
    proposed = [
        {
            "heading_key": "brabant",
            "approved_code": "",
            "approved_theme": "",
            "reviewer": "",
            "proposed_code": "III.D.",
            "proposal_confidence": "0.9100",
        }
    ]
    existing = [
        {
            "heading_key": "brabant",
            "approved_code": "III.B.2.a.",
            "approved_theme": "local",
            "reviewer": "editor",
            "proposed_code": "II.A.",
        }
    ]
    merged = refresh_crosswalk(proposed, existing)
    assert merged[0]["approved_code"] == "III.B.2.a."
    assert merged[0]["approved_theme"] == "local"
    assert merged[0]["reviewer"] == "editor"
    assert merged[0]["proposed_code"] == "III.D."


def test_an_empty_review_cell_can_be_filled():
    proposed = [{"heading_key": "k", "approved_code": "III.D.", "approved_theme": "", "reviewer": "rule"}]
    existing = [{"heading_key": "k", "approved_code": "", "approved_theme": "", "reviewer": ""}]
    merged = refresh_crosswalk(proposed, existing)
    assert merged[0]["approved_code"] == "III.D."
    assert merged[0]["reviewer"] == "rule"


def test_approved_heading_beats_the_classifier():
    record = _record(bhb_codes=["II.A."])
    row = {"approved_code": "III.D.2.a.", "approved_theme": "", "reviewer": "rule", "proposed_code": "I.A.", "proposal_confidence": "0.99"}
    categories = categories_for(record, row, [], Scored("III.C.", 0.95, [("economic", 0.9)]), 0.70, 0.60)
    primary = next(item for item in categories if item.primary)
    assert primary.code == "III.D.2.a."
    assert primary.source == "heading-rule"
    assert primary.machine is False
    assert any(item.code == "II.A." and item.source == "vsmart" and not item.primary for item in categories)


def test_broad_heading_uses_the_classifier_and_not_the_proposal():
    record = _record()
    row = {
        "approved_code": "BROAD",
        "approved_theme": "",
        "reviewer": "editor",
        "proposed_code": "III.D.",
        "proposal_confidence": "0.99",
    }
    categories = categories_for(record, row, [], Scored("III.D.2.", 0.40, [("political", 0.81)]), 0.70, 0.60)
    assert categories[0].code is None
    assert categories[0].theme == "political"
    assert categories[0].machine is True
    assert categories[0].primary is True
    assert all(item.code != "III.D." for item in categories)


def test_unreviewed_proposal_needs_eighty_percent():
    record = _record()
    low = {"approved_code": "", "proposed_code": "III.B.", "proposal_confidence": "0.79", "approved_theme": "", "reviewer": ""}
    assert categories_for(record, low, [], None, 0.70, 0.60) == []
    high = dict(low, proposal_confidence="0.80")
    categories = categories_for(record, high, [], None, 0.70, 0.60)
    assert categories[0].source == "crosswalk"
    assert categories[0].machine is True
    assert categories[0].code == "III.B."


def test_see_also_stays_secondary():
    record = _record()
    other = {"approved_code": "I.A.", "approved_theme": "", "reviewer": "rule"}
    categories = categories_for(record, None, [other], Scored("III.D.", 0.91), 0.70, 0.60)
    primary = next(item for item in categories if item.primary)
    assert primary.source == "classifier"
    see_also = next(item for item in categories if item.source == "see-also")
    assert see_also.primary is False
    assert see_also.machine is False
    assert see_also.code == "I.A."


def test_below_both_thresholds_stays_unclassified():
    record = _record()
    categories = categories_for(record, None, [], Scored("III.D.", 0.69, [("political", 0.59)]), 0.70, 0.60)
    assert categories == []


def test_theme_threshold_is_the_smallest_that_holds_ninety_percent():
    scored = [({"political": 0.61}, set()) for _ in range(8)]
    scored.append(({"political": 0.61}, {"political"}))
    scored.extend(({"political": 0.80}, {"political"}) for _ in range(10))
    tau, precision, _coverage = choose_tau_theme(scored)
    assert tau == 0.62
    assert precision is not None and precision >= 0.90


def test_vsmart_code_is_the_primary_category():
    record = _record(source="vsmart", bgb_year=2011, bhb_codes=["III.D.2.a.", "III.D.2.b."])
    categories = categories_for(record, None, [], None, 0.70, 0.60)
    assert [item.code for item in categories] == ["III.D.2.a.", "III.D.2.b."]
    assert categories[0].primary is True
    assert categories[0].machine is False
    assert categories[1].primary is False


def test_a_heading_takes_the_code_of_its_respelled_siblings():
    # Guy Vanthemsche, 10 Nov 2026: BGB 1980 prints the banking heading as "e. Moyens de payement …" under
    # "3. Histoire Économique"; 1982–1990 print it under "c. Histoire Économique / Généralités", and only that
    # spelling had the code of finance.
    from collections import Counter

    from bhb.categorise import _Group, sibling_codes

    contemporary = "G. Époque contemporaine — Hedendaags tijdvak, 1789–1980"
    banks = "Moyens de payement, banques, compagnies d’assurance — Betalingsmiddelen, banken, verzekeringsmaatschappijen"
    later = ("III. Histoire par Époques", contemporary, "c. Histoire Économique", "Généralités — Algemene werken", banks)
    earlier = ("III. Histoire par Époques", contemporary, "3. Histoire Économique", f"e. {banks}")
    medieval = ("III. Histoire par Époques", "B. Le moyen âge — De middeleeuwen", "3. Histoire Économique", f"e. {banks}")
    groups = {key: _Group(key=key, paths=Counter({path: 1}), n_entries=1)
              for key, path in (("later", later), ("earlier", earlier), ("medieval", medieval))}
    rows = {"later": {"model_code": "III.D.2.b.5.", "model_confidence": "0.36"}, "earlier": {}, "medieval": {}}
    assert sibling_codes(groups, rows) == 1
    assert rows["earlier"]["model_code"] == "III.D.2.b.5."
    # Another period does not take it.
    assert "model_code" not in rows["medieval"]


def test_an_unnumbered_heading_names_the_deeper_code():
    from bhb.categorise import finer_codes
    from bhb.scheme import load_scheme

    scheme = load_scheme()
    above = ["III. Histoire par Époques", "D. Époque contemporaine", "2. Histoire par secteurs fonctionnels",
             "b. La vie économique — Het economische leven"]
    assert finer_codes([*above, "Les finances - De financiën"], above[-1], "III.D.2.b.", scheme) == ["III.D.2.b.5."]
    # Under "Généralités" too; a wording that names no code leaves it.
    culture = [*above[:3], "e. Histoire culturelle - Cultuurgeschiedenis", "Généralités - Algemeenheden"]
    assert finer_codes([*culture, "(c) L’architecture - De architectuur"], culture[3], "III.D.2.e.", scheme) == ["III.D.2.e.6.c."]
    assert finer_codes([*culture, "(a) Historiens; archéologues - Historici; archeologen"], culture[3], "III.D.2.e.", scheme) == []
    # A heading that names two codes has both.
    politics = [*above[:3], "a. Les institutions, le droit, l’histoire politique et militaire"]
    named = finer_codes([*politics, "(b) Les élections; les partis; le personnel politique - De verkiezingen; de partijen"],
                        politics[-1], "III.D.2.a.", scheme)
    assert named == ["III.D.2.a.2.b.1.", "III.D.2.a.2.b.2."]


def test_a_rule_row_takes_the_rules_deeper_code_but_a_review_stays():
    from bhb.categorise import refresh_crosswalk

    fresh = [{"heading_key": "k", "approved_code": "III.D.2.b.5.", "reviewer": "rule", "approved_theme": "", "note": ""},
             {"heading_key": "r", "approved_code": "III.D.2.b.5.", "reviewer": "rule", "approved_theme": "", "note": ""}]
    old = [{"heading_key": "k", "approved_code": "III.D.2.b.", "reviewer": "rule", "approved_theme": "", "note": ""},
           {"heading_key": "r", "approved_code": "III.D.2.b.", "reviewer": "Sofie", "approved_theme": "", "note": "checked"}]
    rows = {row["heading_key"]: row for row in refresh_crosswalk(fresh, old)}
    assert rows["k"]["approved_code"] == "III.D.2.b.5."
    assert rows["r"]["approved_code"] == "III.D.2.b." and rows["r"]["note"] == "checked"
