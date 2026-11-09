"""The check of the title translations (bhb/translation_check.py), with the model replaced by a stand-in."""

from bhb import translation_check as tc
from bhb.citations import Reply


def _reply(content):
    return Reply(content, "m", None, 0.0, 0, 0, 0, 0.0, False)


def test_a_batch_whose_ids_come_back_wrong_is_asked_again_title_by_title(monkeypatch, tmp_path):
    entries = [tc.Entry("a", "Titre a", ["fr"], {"nl": "Titel a"}), tc.Entry("b", "Titre b", ["fr"], {"nl": "Titel a"})]
    asked = []

    def fake_call(body, cache):
        ids = body["response_format"]["json_schema"]["schema"]["properties"]["items"]["items"]["properties"]["id"]["enum"]
        asked.append(ids)
        if len(ids) > 1:
            return _reply({"items": [{"id": "b", "nl": "ok", "fr": "none", "en": "none"}]})
        verdict = "ok" if ids == ["a"] else "wrong"
        return _reply({"items": [{"id": ids[0], "nl": verdict, "fr": "none", "en": "none"}]})

    monkeypatch.setattr(tc, "call", fake_call)
    verdicts, _ = tc.check(entries, tmp_path)
    assert asked == [["a", "b"], ["a"], ["b"]]
    assert verdicts == {"a": {"nl": "ok", "fr": "none", "en": "none"}, "b": {"nl": "wrong", "fr": "none", "en": "none"}}


def test_a_new_translation_replaces_the_old_one_with_the_checks_verdict(monkeypatch, tmp_path):
    entry = tc.Entry("b", "Le Vatican et la course à la guerre", ["fr"], {"nl": "Mgr. Simon Deploige aan het Vaticaan", "en": "The Vatican"})
    monkeypatch.setattr(tc, "ask_titles", lambda items, model, cache: ({"b": {"nl": "Het Vaticaan en de oorlog", "fr": None, "en": "x"}}, _reply({})))
    monkeypatch.setattr(tc, "call", lambda body, cache: _reply({"items": [{"id": "b", "nl": "ok", "fr": "none", "en": "ok"}]}))
    assert tc.repair(entry, ["nl"], tmp_path)[0] == {"nl": ("Het Vaticaan en de oorlog", "ok")}
    # A strict verdict on the new translation does not throw it away: made for its title alone, it has no neighbour's text.
    monkeypatch.setattr(tc, "call", lambda body, cache: _reply({"items": [{"id": "b", "nl": "wrong", "fr": "none", "en": "ok"}]}))
    assert tc.repair(entry, ["nl"], tmp_path)[0] == {"nl": ("Het Vaticaan en de oorlog", "wrong")}
