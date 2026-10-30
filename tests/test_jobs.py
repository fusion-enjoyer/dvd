import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from dvd import jobs


@pytest.fixture
def queue(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DVD_QUEUE", str(tmp_path / "queue.yaml"))
    return tmp_path


def test_jobs_run_in_order_and_a_failure_does_not_stop_the_queue(queue: Path):
    a, b, c = (queue / f"{n}.dvd.yaml" for n in "abc")
    jobs.add_job(a)
    jobs.add_job(a)  # already waiting: not twice
    jobs.add_job(b)
    jobs.add_job(c)
    assert [Path(j.project).name for j in jobs.load_jobs()] == ["a.dvd.yaml", "b.dvd.yaml",
                                                                "c.dvd.yaml"]  # fmt: skip
    built, seen = [], []

    def build(path: Path, progress=None):
        built.append(path.name)
        progress("title 1 video", 0.5)
        if path.name == "b.dvd.yaml":
            raise RuntimeError("the titles do not fit on DVD5")
        return SimpleNamespace(iso=path.with_suffix(".iso"), video_ts=path.parent)

    ran = jobs.run_queue(build, lambda job, stage, f: seen.append((Path(job.project).name, stage)),
                         stop=lambda: len(built) >= 2)  # fmt: skip
    assert built == ["a.dvd.yaml", "b.dvd.yaml"] and len(ran) == 2
    assert seen[0] == ("a.dvd.yaml", "title 1 video")
    states = [(j.state, j.message) for j in jobs.load_jobs()]
    assert states[0] == ("done", str(a.with_suffix(".iso")))
    assert states[1] == ("failed", "the titles do not fit on DVD5")
    assert states[2] == ("waiting", "")  # stopped between jobs
    # A job cut off while running is built again next time.
    left = jobs.load_jobs()
    left[2].state = "running"
    jobs.save_jobs(left)
    assert [Path(j.project).name for j in jobs.run_queue(build)] == ["c.dvd.yaml"]
    jobs.clear_finished()
    assert jobs.load_jobs() == []


def test_what_happens_after_the_queue():
    assert jobs.after_command("nothing") is None
    assert jobs.after_command("sleep")[0] == "rundll32.exe"
    shutdown = jobs.after_command("shutdown")
    assert shutdown[:4] == ["shutdown.exe", "/s", "/t", "120"]  # two minutes to cancel
    with pytest.raises(ValueError):
        jobs.after_command("reboot")


def test_pause_stops_the_programs_a_build_started(tmp_path: Path):
    from dvd.pause import Pause, children

    out = tmp_path / "ticks.txt"
    script = ("import time, sys\n"
              "while True:\n"
              "    open(sys.argv[1], 'a').write('.')\n"
              "    time.sleep(0.02)\n")  # fmt: skip
    child = subprocess.Popen([sys.executable, "-c", script, str(out)],
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))  # fmt: skip
    try:
        time.sleep(0.5)
        assert child.pid in children()
        pause = Pause()
        pause.pause()
        assert pause.active
        time.sleep(0.2)
        before = out.stat().st_size
        time.sleep(0.5)
        assert out.stat().st_size == before  # nothing happens while paused
        pause.resume()
        time.sleep(0.5)
        assert out.stat().st_size > before and not pause.active
    finally:
        child.kill()
        child.wait()


def test_queue_commands(queue: Path, monkeypatch):
    from typer.testing import CliRunner

    from dvd.cli import app

    project = queue / "film.dvd.yaml"
    project.write_text("x", encoding="utf-8")
    runner = CliRunner()
    assert runner.invoke(app, ["queue", "add", str(project)]).exit_code == 0
    assert "waiting" in runner.invoke(app, ["queue", "list"]).output
    monkeypatch.setattr(jobs, "do_after", lambda action: None)
    import dvd.build

    monkeypatch.setattr(dvd.build, "build", lambda path, progress=None: SimpleNamespace(
        iso=path.with_suffix(".iso"), video_ts=path.parent))  # fmt: skip
    out = runner.invoke(app, ["queue", "run", "--then", "nothing"])
    assert out.exit_code == 0 and "1 built, 0 failed" in out.output
    assert runner.invoke(app, ["queue", "run", "--then", "reboot"]).exit_code == 1
    assert runner.invoke(app, ["queue", "remove", "5"]).exit_code == 1
    runner.invoke(app, ["queue", "clear"])
    assert "the queue is empty" in runner.invoke(app, ["queue", "list"]).output
