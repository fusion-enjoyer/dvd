r"""The job queue: projects built one after another (%APPDATA%\DVD Studyo\queue.yaml;
DVD_QUEUE points elsewhere), and what the computer does when the last one is done.

The file is the queue: the window and `dvd queue` both read and write it, so a queue made
in one is seen in the other. A job left "running" when the program closed is built again
the next time the queue runs.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import yaml

STATES = ("waiting", "running", "done", "failed")
AFTER = ("nothing", "sleep", "shutdown")
SHUTDOWN_DELAY = 120  # seconds: `shutdown /a` (or the window Windows shows) cancels it


@dataclass
class Job:
    project: str  # project file, absolute
    state: str = "waiting"
    message: str = ""  # where the disc went, or why it failed
    finished: str = ""  # when, ISO time


def queue_file() -> Path:
    if env := os.environ.get("DVD_QUEUE"):
        return Path(env)
    base = Path(os.environ.get("APPDATA") or Path.home() / ".config")
    return base / "DVD Studyo" / "queue.yaml"


def load_jobs() -> list[Job]:
    path = queue_file()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else []
    except (OSError, yaml.YAMLError):
        return []
    jobs = []
    for item in data if isinstance(data, list) else []:
        if isinstance(item, dict) and item.get("project"):
            job = Job(str(item["project"]), str(item.get("state", "waiting")),
                      str(item.get("message", "")), str(item.get("finished", "")))  # fmt: skip
            if job.state not in STATES:
                job.state = "waiting"
            jobs.append(job)
    return jobs


def save_jobs(jobs: list[Job]) -> None:
    path = queue_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump([asdict(j) for j in jobs], allow_unicode=True,
                                   sort_keys=False), encoding="utf-8")  # fmt: skip


def add_job(project: Path) -> Job:
    """Queue a project (once: a project already waiting is not added again)."""
    jobs = load_jobs()
    path = str(Path(project).resolve())
    for job in jobs:
        if job.project == path and job.state == "waiting":
            return job
    job = Job(path)
    jobs.append(job)
    save_jobs(jobs)
    return job


def remove_job(index: int) -> None:
    jobs = load_jobs()
    if not 0 <= index < len(jobs):
        raise IndexError(f"no job {index + 1}")
    jobs.pop(index)
    save_jobs(jobs)


def clear_finished() -> None:
    save_jobs([j for j in load_jobs() if j.state == "waiting"])


Progress = Callable[[str, float], None]


def run_queue(build: Callable | None = None, progress: Callable[[Job, str, float], None]
              | None = None, stop: Callable[[], bool] = lambda: False) -> list[Job]:  # fmt: skip
    """Build the waiting jobs in order; `stop` is asked between jobs. The jobs it ran."""
    if build is None:
        from dvd.build import build
    jobs = load_jobs()
    for job in jobs:  # only one queue runs at a time: these were cut off
        if job.state == "running":
            job.state = "waiting"
    save_jobs(jobs)
    ran = []
    while not stop():
        jobs = load_jobs()
        k = next((i for i, j in enumerate(jobs) if j.state == "waiting"), None)
        if k is None:
            break
        job = jobs[k]
        job.state = "running"
        save_jobs(jobs)
        report = (lambda s, f, j=job: progress(j, s, f)) if progress else None
        try:
            result = build(Path(job.project), progress=report)
            job.state = "done"
            job.message = str(result.iso or result.video_ts)
        except Exception as exc:  # noqa: BLE001 (any failure ends this job, not the queue)
            job.state = "failed"
            job.message = str(exc) or type(exc).__name__
        job.finished = datetime.now().isoformat(timespec="seconds")
        jobs = load_jobs()  # the queue may have changed while this one was building
        for other in jobs:
            if other.project == job.project and other.state == "running":
                other.state, other.message, other.finished = job.state, job.message, job.finished
                break
        save_jobs(jobs)
        ran.append(job)
    return ran


def after_command(action: str) -> list[str] | None:
    """The command that puts the computer to sleep or shuts it down (Windows), or None."""
    if action not in AFTER:
        raise ValueError(f"after the queue: one of {', '.join(AFTER)}")
    if action == "sleep":
        return ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"]
    if action == "shutdown":
        return ["shutdown.exe", "/s", "/t", str(SHUTDOWN_DELAY), "/c",
                "DVD Studyo: kuyruk bitti, bilgisayar kapanıyor (iptal: shutdown /a)"]  # fmt: skip
    return None


def do_after(action: str) -> None:
    """Carry out `after_command(action)`."""
    command = after_command(action)
    if command is not None:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(command, check=False, creationflags=flags)
