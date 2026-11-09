from bhb.heading_review import Group, agreement, group_key, groups_of, parse


def test_headings_that_differ_in_numbering_footnotes_and_articles_are_one_group():
    a = group_key("Bibliographie et Sciences Auxiliaires / G. Sciences linguistiques / 3. Toponymie")
    b = group_key("Bibliographie et Sciences Auxiliaires / H. Sciences linguistiques (¹) / 4) Toponymie")
    assert a == b
    assert group_key("La vie économique / Les finances") != group_key("La vie économique / Le commerce")


def test_only_unreviewed_headings_of_the_old_volumes_are_grouped():
    rows = [
        {"era": "1962-1992", "heading_key": "a", "example_fr": "II. Les arts", "n_entries": "40", "approved_code": ""},
        {"era": "1962-1992", "heading_key": "b", "example_fr": "III. Les arts (¹)", "n_entries": "10", "approved_code": ""},
        {"era": "1962-1992", "heading_key": "c", "example_fr": "Les finances", "n_entries": "9", "approved_code": "III.D.2.b.5."},
        {"era": "1993-2008", "heading_key": "d", "example_fr": "Les métiers", "n_entries": "9", "approved_code": ""},
    ]
    groups = groups_of(rows)
    assert len(groups) == 1
    group = next(iter(groups.values()))
    assert group.n == 50 and group.main["heading_key"] == "a"


def test_an_answer_counts_only_with_a_code_that_was_offered():
    offered = [("III.D.2.b.", 0.6), ("III.D.2.b.5.", None)]
    assert parse('{"code": "III.D.2.b.5.", "fit": "part"}', offered) == ("III.D.2.b.5.", "part")
    assert parse('Here: {"code": "III.D.2.b.5", "fit": "same"}', offered) == ("III.D.2.b.5.", "same")
    assert parse('{"code": "BROAD"}', offered) == ("BROAD", "")
    assert parse('{"code": "I.A.", "fit": "same"}', offered) == ("", "")
    assert parse("no json", offered) == ("", "")


def test_agreement_with_the_classifier():
    votes = [("III.D.2.b.", 0.6), ("III.D.2.c.", 0.2)]
    assert agreement("III.D.2.b.", votes) == "agree"
    assert agreement("III.D.2.b.5.", votes) == "related"
    assert agreement("III.D.2.c.", votes) == "differ"
    assert agreement("BROAD", votes) == ""
    assert Group("k").n == 0


def test_a_proposal_is_taken_only_when_model_and_classifier_agree_and_it_fits():
    from bhb.heading_review import accepted

    base = {"proposed_code": "III.D.2.b.5.", "agreement": "agree", "fit": "same", "n_entries": "40"}
    assert accepted(base)
    assert accepted({**base, "agreement": "related", "fit": "part"})
    assert not accepted({**base, "agreement": "differ"})
    assert not accepted({**base, "fit": "wider"})
    assert not accepted({**base, "proposed_code": "BROAD"})
    assert not accepted({**base, "n_entries": "4"})


def test_an_accepted_model_code_comes_after_a_reviewer_and_before_the_classifier():
    from bhb.categorise import Scored, categories_for
    from bhb.model import Record

    record = Record(id="bhb:1969-1", source="print-straive", bgb_year=1969)
    row = {"heading_key": "k", "approved_code": "", "model_code": "III.D.2.b.5.", "model_confidence": "0.62"}
    found = categories_for(record, row, [], Scored("III.D.2.b.", 0.9), 0.7, 0.6)
    assert found[0].code == "III.D.2.b.5." and found[0].machine and found[0].source == "heading-model"
    reviewed = categories_for(record, {**row, "approved_code": "III.D.2.c."}, [], None, 0.7, 0.6)
    assert reviewed[0].code == "III.D.2.c." and not reviewed[0].machine
