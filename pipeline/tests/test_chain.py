"""The release chain (bhb chain): the README's order, the choice of steps, and the guard before the paid step."""

import pytest

from bhb import chain
from bhb.paths import repo_root

DRY_RUN = """164,397 entries to parse in 21,401 batches; mistralai/mistral-small-2603, prompt v4; credit left: $28.88
dry run: 92 parse requests not in the cache (not sent)
245,774 titles: 245,548 translated before from the same text, 226 to translate in 10 requests
dry run: nothing sent; 0 of the 10 requests are in the cache
"""


def test_steps_follow_the_readme_order():
    text = (repo_root() / "pipeline" / "README.md").read_text(encoding="utf-8")
    paragraph = text[text.index("A release is made from a full run"):]
    position = 0
    for step in chain.STEPS:
        if step.map_only:  # named in a parenthesis after `bhb topicmap apply`
            continue
        found = paragraph.find(f"`bhb {' '.join(step.args)}`", position)
        if found < 0:  # the README names a repeated step once in running text ("then `bhb journals apply` once before …")
            found = paragraph.find(f"bhb {' '.join(step.args)}", position)
        assert found >= 0, f"step {step.label} not found in the README after position {position}"
        position = found + 1


def test_plan_chooses_steps_and_flags():
    numbers = [number for number, _, _ in chain.plan()]
    assert numbers == [n for n in range(1, len(chain.STEPS) + 1) if not chain.STEPS[n - 1].map_only]
    with_map = chain.plan("citations-apply", with_map=True)
    assert with_map[0][2] == ["citations", "apply"]
    assert ["topicmap", "layout"] in [args for _, _, args in with_map]
    assert chain.plan(1, 1, build_flags=["--with-manuscripts"])[0][2] == ["build", "--with-manuscripts"]
    assert [args for _, _, args in chain.plan("5", "5")] == [["citations", "run"]]
    with pytest.raises(SystemExit):
        chain.plan("release", "build")
    with pytest.raises(SystemExit):
        chain.plan("nonsense")


def test_dry_run_counts():
    assert chain.dry_run_counts(DRY_RUN) == (92, 10)
    assert chain.dry_run_counts("something else") is None


class FakeRunner:
    def __init__(self, fail=None, dry_output=DRY_RUN):
        self.calls, self.fail, self.dry_output = [], fail, dry_output

    def __call__(self, args, log):
        self.calls.append(args)
        if "--dry-run" in args:
            return 0, self.dry_output
        return (1 if args == self.fail else 0), ""


def test_guard_stops_before_paying_more_than_allowed(tmp_path):
    runner = FakeRunner()
    code = chain.run_chain(chain.plan("language", "citations-apply"), tmp_path / "chain.log", 50, 10, runner)
    assert code == 3
    assert runner.calls == [["language", "apply"], ["citations", "run", "--dry-run"]]
    assert "STOP before the paid step" in (tmp_path / "chain.log").read_text()


def test_guard_lets_the_allowed_run_through(tmp_path):
    runner = FakeRunner()
    code = chain.run_chain(chain.plan("citations-run", "citations-apply"), tmp_path / "chain.log", 92, 10, runner)
    assert code == 0
    assert runner.calls == [["citations", "run", "--dry-run"], ["citations", "run"], ["citations", "apply"]]


def test_guard_stops_without_counts_and_a_failed_step_stops_the_chain(tmp_path):
    assert chain.run_chain(chain.plan(5, 5), tmp_path / "a.log", 10**6, 10**6, FakeRunner(dry_output="")) == 3
    runner = FakeRunner(fail=["similar"])
    assert chain.run_chain(chain.plan("citations-apply", "facets"), tmp_path / "b.log", runner=runner) == 1
    assert runner.calls == [["citations", "apply"], ["similar"]]
