"""One Java practice window in an editor image, for the tests that read a live workbench.

Not a test module. `container(image, kind)` starts a container of `image`
with the image's own command line (`activation.start`) and bind-mounts a folder
holding one Java file and the workspace settings a study page writes for it;
`browser(...)` opens a headless browser at `about:blank` with its debugger on
and yields an `Opened`, whose `url` is the workbench URL a study page builds
for that file; `opened(image, kind)` is both. Each removes what it started,
whatever happened.

⭐ The browser starts BLANK so a test decides when the workbench opens, and can
navigate away (the reader closing the frame) and back (the reader reloading).
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docker" / "editor"))

import activation  # noqa: E402
import cdp  # noqa: E402
import probe  # noqa: E402

MAIN = "Practice.java"
SOURCE = """package practice;

public class Practice {
    public static int twice(int value) {
        return value * 2;
    }
}
"""
#: What a study page's settings do to a keyword: bold, the page's keyword weight.
#: ⭐ The only customisation written here, so a bold token is this file's doing.
SETTINGS = {
    "editor.tokenColorCustomizations": {
        "textMateRules": [{"scope": ["keyword", "storage.modifier", "storage.type"],
                           "settings": {"fontStyle": "bold"}}],
    },
}


@dataclass(frozen=True)
class Opened:
    name: str
    port: int
    debug: int
    page: dict
    browser: subprocess.Popen

    @property
    def url(self) -> str:
        return activation.workbench_url(self.port, name=MAIN)


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, **kwargs)


@contextlib.contextmanager
def container(image: str, kind: str):
    """One container of `image` serving the Java practice folder: yields (name, port, scratch)."""
    name = f"{kind}-probe-{uuid.uuid4().hex[:12]}"
    with tempfile.TemporaryDirectory(prefix=f"{kind}-probe-") as scratch:
        sources = Path(scratch) / "sources"
        (sources / ".vscode").mkdir(parents=True)
        (sources / MAIN).write_text(SOURCE, encoding="utf-8")
        (sources / ".vscode" / "settings.json").write_text(json.dumps(SETTINGS), encoding="utf-8")
        for path in (Path(scratch), sources, sources / ".vscode"):
            path.chmod(0o755)
        try:
            activation.start(image, name, sources)
            port = activation.published_port(name)
            activation.wait_for_health(port)
            yield name, port, Path(scratch)
        finally:
            run(["docker", "rm", "-f", name])


@contextlib.contextmanager
def browser(name: str, port: int, profile: Path):
    """A headless browser at `about:blank`, its debugger on; yields an `Opened`."""
    debug = probe.free_port()
    session = subprocess.Popen(
        [activation.browser(), *activation.BROWSER_FLAGS, f"--remote-debugging-port={debug}",
         f"--user-data-dir={profile}", "about:blank"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        yield Opened(name, port, debug, cdp.wait_for_target(debug, "about:blank"), session)
    finally:
        if session.poll() is None:
            session.terminate()
            try:
                session.wait(timeout=20)
            except subprocess.TimeoutExpired:
                session.kill()


@contextlib.contextmanager
def opened(image: str, kind: str):
    """One container and one browser in it: the common case."""
    with container(image, kind) as (name, port, scratch), browser(name, port, scratch / "profile") as page:
        yield page


def processes(name: str) -> list[tuple[int, str]]:
    """Every process in the container, as (pid, command line)."""
    listing = run(["docker", "exec", name, "ps", "-ww", "-eo", "pid=,args="]).stdout
    found = []
    for line in listing.splitlines():
        pid, _, args = line.strip().partition(" ")
        if pid.isdigit():
            found.append((int(pid), args))
    return found


def extension_hosts(name: str) -> list[int]:
    return [pid for pid, args in processes(name) if "--type=extensionHost" in args]


def language_servers(name: str) -> list[int]:
    """The Java language servers: a JVM running the Eclipse launcher, which is jdt.ls."""
    return [pid for pid, args in processes(name)
            if args.split(" ", 1)[0].endswith("/bin/java") and "org.eclipse.equinox.launcher" in args]


def derived(tag: str, prefix: str, steps: str) -> str:
    """`tag` with `steps` applied as ONE derived layer, so the plant is provably the only difference."""
    image = f"{prefix}:{uuid.uuid4().hex[:12]}"
    with tempfile.TemporaryDirectory(prefix=f"{prefix}-") as context:
        Path(context, "Dockerfile").write_text(f"FROM {tag}\nUSER root\n{steps}\nUSER 1000\n", encoding="utf-8")
        done = run(["docker", "build", "-t", image, context])
    if done.returncode != 0:
        raise AssertionError(f"the plant did not build:\n{done.stderr}")
    return image
