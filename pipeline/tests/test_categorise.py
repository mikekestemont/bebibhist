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
