"""The full citation pass (bhb citations run) with the model replaced by stand-ins: a title translated before from the
same text keeps its translation, only the others are asked and checked, and a dry run sends nothing."""

import json

import pytest

from bhb import cli, citations
from bhb import translation_check as tc
from bhb.citations import Reply
from bhb.io_utils import write_jsonl
from bhb.model import Provenance, Record


def _reply(content=None, error=None):
    return Reply(content, "m", None, 0.0, 0, 0, 0, 0.0, True, error)


def _records():
    return [Record(id=f"bhb:1970-{n}", source="print-straive", bgb_year=1970, printed=f"Auteur (A.). Titre {n}. Bruxelles, 1970.",
                   title=f"Titre {n}", language_suggested=["fr"], section_path=["I"], provenance=Provenance()) for n in (1, 2, 3)]


@pytest.fixture
def build(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "build_dir", lambda: tmp_path)
    monkeypatch.setattr(citations, "credit", lambda: None)
    monkeypatch.setattr(citations, "OFFLINE", False)
    write_jsonl(tmp_path / "records.jsonl", _records())
    run = tmp_path / "citations" / "run"
    run.mkdir(parents=True)
    # Titre 1 was translated from the same text; Titre 2 from another text; Titre 3 never.
    rows = [{"id": "bhb:1970-1", "model": "m", "nl": "Titel 1", "fr": None, "en": "Title 1", "source": "Titre 1", "languages": ["fr"]},
            {"id": "bhb:1970-2", "model": "m", "nl": "Oude titel", "fr": None, "en": "Old title", "source": "Titre deux", "languages": ["fr"]}]
    (run / "translations.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    monkeypatch.setattr(citations, "ask_parse", lambda batch, model, cache, *rest, **kw: (
        {item.id: {"title": item.printed.split(". ")[1], "subtitle": None, "title_translated": None, "persons": [], "type": "book"}
         for item in batch.items}, [_reply({})]))
    return tmp_path


def test_only_titles_not_translated_before_from_the_same_text_are_asked_and_checked(build, monkeypatch):
    asked, checked = [], {}
    monkeypatch.setattr(citations, "ask_titles", lambda items, model, cache, *rest, **kw: (
        asked.extend(item.id for item in items) or {item.id: {"nl": "Nieuw " + item.printed, "fr": None, "en": "New " + item.printed} for item in items},
        _reply({})))
    monkeypatch.setattr(tc, "run", lambda out, records, cache, workers=8, only=None: checked.setdefault("only", only))
    cli._citations_run("m", None, 1, True)
    assert sorted(asked) == ["bhb:1970-2", "bhb:1970-3"]
    assert checked["only"] == {"bhb:1970-2", "bhb:1970-3"}
    rows = {row["id"]: row for row in map(json.loads, (build / "citations" / "run" / "translations.jsonl").read_text().splitlines())}
    assert rows["bhb:1970-1"]["nl"] == "Titel 1" and rows["bhb:1970-2"]["nl"] == "Nieuw Titre 2"
    assert rows["bhb:1970-3"]["source"] == "Titre 3" and rows["bhb:1970-3"]["languages"] == ["fr"]
    assert (build / "citations" / "run" / "translations.previous.jsonl").is_file()


def test_a_dry_run_sends_nothing_and_leaves_the_run_alone(build, monkeypatch, capsys):
    monkeypatch.setattr(citations, "ask_titles", lambda *args, **kw: pytest.fail("a dry run asked for translations"))
    monkeypatch.setattr(tc, "run", lambda *args, **kw: pytest.fail("a dry run checked translations"))
    before = (build / "citations" / "run" / "translations.jsonl").read_text()
    cli._citations_run("m", None, 1, True, dry_run=True)
    assert "1 translated before from the same text, 2 to translate in 1 requests" in capsys.readouterr().out
    assert (build / "citations" / "run" / "translations.jsonl").read_text() == before
    assert (build / "citations" / "run-dry" / "answers.jsonl").is_file()


def test_offline_a_request_not_in_the_cache_is_not_sent(tmp_path, monkeypatch):
    monkeypatch.setattr(citations, "OFFLINE", True)
    monkeypatch.setattr(citations.urllib.request, "urlopen", lambda *a, **kw: pytest.fail("sent"))
    reply = citations.call({"model": "m", "messages": []}, tmp_path)
    assert reply.content is None and reply.error.startswith("offline") and not reply.cached


def test_the_check_judges_a_translation_against_its_source_and_keeps_earlier_changes(tmp_path, monkeypatch):
    write_jsonl(tmp_path / "records.jsonl", _records())
    rows = [{"id": "bhb:1970-1", "nl": "Titel 1", "source": "Titre 1"},
            {"id": "bhb:1970-2", "nl": "Fout", "source": "Le vrai titre 2"}]
    (tmp_path / "translations.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    (tmp_path / "translation-check.csv").write_text("id,language,title,old,new,check\nbhb:1970-1,nl,Titre 1,X,Titel 1,ok\n", encoding="utf-8")
    seen = []

    def fake_check(entries, cache, model=tc.MODEL):
        seen.extend((entry.id, entry.title) for entry in entries)
        return {entry.id: {"nl": "wrong", "fr": "none", "en": "none"} for entry in entries}, []

    monkeypatch.setattr(tc, "check", fake_check)
    monkeypatch.setattr(tc, "repair", lambda entry, wrong, cache: ({"nl": ("Goed", "ok")}, []))
    tc.run(tmp_path, tmp_path / "records.jsonl", tmp_path / "cache", workers=1, only={"bhb:1970-2"}, log=lambda *a: None)
    assert seen == [("bhb:1970-2", "Le vrai titre 2")]
    after = {row["id"]: row for row in map(json.loads, (tmp_path / "translations.jsonl").read_text().splitlines())}
    assert after["bhb:1970-2"]["nl"] == "Goed" and after["bhb:1970-1"]["nl"] == "Titel 1"
    sheet = (tmp_path / "translation-check.csv").read_text()
    assert "bhb:1970-1,nl,Titre 1,X,Titel 1,ok" in sheet and "bhb:1970-2,nl,Le vrai titre 2,Fout,Goed,ok" in sheet
