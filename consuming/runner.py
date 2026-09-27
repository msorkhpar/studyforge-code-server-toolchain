"""The runner block of `consuming.json`: what it must say, and the run line it renders.

**What it does.** The runner image has no compose file — a reader starts one
container by hand and the framework execs into it — so this module is the
runner's half of what `consuming.py` is for the editor: it checks the `runner`
block against the rulings a consumer inherits, and renders from it the
`docker run` and `docker exec` lines that the README documents.

**How you use it.** From the component root:

    python3 consuming/consuming.py --check      # every block, this one included
    python3 consuming/consuming.py --run-line   # the run line, from the contract
    python3 consuming/consuming.py --run-line --powershell   # the same, for PowerShell

`findings(runner)` returns what is wrong with the block, empty when nothing is;
`run_line(runner, ...)` and `exec_line(runner, ...)` return the two documented
lines, and **refuse** a block with a finding rather than printing one that
breaks a ruling.

**Depends on.** The standard library only. ⛔ It reads no Dockerfile, starts no
container and mounts no socket.

## ⛔ Why this is a module of its own and not more branches in `consuming.py`

The split is at the BLOCK, not at the ruling, because three of
the editor's five finding groups — the published port, the named volumes, the
health check — do not apply to an image that listens on nothing, mounts one
bind and answers no request. Folding "unless it is the runner" into each of
them would have made every editor check read as a pair of exceptions. So the
rulings the two blocks SHARE (no Docker socket, the owner's uid:gid, a bind that exists
first) are asserted here in the runner's own terms, and `consuming.findings`
calls one function per block.

## ⛔ Why the README still carries the run line

A consumer copies a command out of prose; that is what prose is for. What
was wrong was never the sentence, it is the sentence being the
only copy — so the framework had to re-derive a run shape by parsing it. The
block is now the authority, and a test asserts the documented line is what this
module renders from it. Prose that drifts is a red test, not a stale
instruction a reader follows.
"""

from __future__ import annotations

BLOCK = "runner"
#: The two shells a run line is rendered for: a POSIX shell, and PowerShell.
POSIX, POWERSHELL = "posix", "powershell"
#: What makes a value one POSIX shell's: a substitution or a variable.
SUBSTITUTES = ("$(", "`", "${")
#: The one thing a consumer's shell must not evaluate away: the uid:gid
#: substitution is written in double quotes, never single ones.
QUOTED = '"{}"'


class Refused(ValueError):
    """A runner block that will not be rendered, and which ruling it breaks."""


# --------------------------------------------------------------- the rulings
def findings(runner: dict) -> list[str]:
    """What is wrong with the runner block, empty when nothing is."""
    if not runner:
        return [f"the contract declares no {BLOCK} block: the runner's run shape is data, not prose"]
    found: list[str] = []
    found += _socket_findings(runner)
    found += _network_findings(runner)
    found += _user_findings(runner)
    found += _mount_findings(runner)
    found += _idle_findings(runner)
    found += _environment_findings(runner)
    return found


def _socket_findings(runner: dict) -> list[str]:
    """No Docker socket: never, not behind a flag and not only locally."""
    found = []
    if runner.get("docker_socket") is not False:
        found.append("docker_socket is not declared false: the Docker socket is never mounted")
    for mount in runner.get("mounts", []):
        if "docker.sock" in f"{mount.get('host_path', '')}{mount.get('container_path', '')}":
            found.append(f"a mount names the Docker socket: {mount.get('container_path')}; it is never mounted")
    return found


def _network_findings(runner: dict) -> list[str]:
    """Offline, and listening on nothing."""
    found = []
    network = runner.get("network", {})
    if network.get("mode") != "none":
        found.append(f"the network mode is {network.get('mode')!r}: a graded run reaches off the machine, "
                     "and a practice could pass because the reader happened to be online")
    if not network.get("run_flag"):
        found.append("the network names no run flag, so a consumer has nothing to write on the run line")
    if runner.get("ports"):
        found.append("the runner publishes a port: nothing in this image listens, and a published port "
                     "is a surface with no service behind it")
    return found


def _user_findings(runner: dict) -> list[str]:
    """Run as the owner of the sources, or the files a graded run writes are root's."""
    runs_as = runner.get("runs_as", {})
    found = []
    if runs_as.get("uid") == 0 or runs_as.get("gid") == 0:
        found.append("runs_as is root: a graded run writes root-owned build output into the reader's sources")
    if not runs_as.get("run_value") or not runs_as.get("run_flag"):
        found.append("runs_as names no run flag and value, so a consumer has nothing to write after --user")
    elif runs_as.get("required") is not True:
        found.append("runs_as is not required: this image declares no USER, so a run without the flag is root")
    windows = runs_as.get("powershell_run_value")
    if any(mark in str(runs_as.get("run_value", "")) for mark in SUBSTITUTES) and not windows:
        found.append("runs_as's run_value is a POSIX substitution and no powershell_run_value is declared, "
                     "so a consumer on Windows has nothing to write after --user")
    if windows and (any(mark in str(windows) for mark in SUBSTITUTES) or str(windows).split(":")[0] == "0"):
        found.append("runs_as's powershell_run_value is a substitution or root: it is written as it stands")
    if not runs_as.get("compose_key") or not runs_as.get("compose_value"):
        found.append("runs_as names no compose key and value, so a consumer rendering a compose service "
                     "has only a shell substitution compose cannot evaluate")
    return found


def _mount_findings(runner: dict) -> list[str]:
    """One bind, at the workspace, and its source exists before the container starts."""
    workspace = runner.get("workspace", {})
    root = workspace.get("container_path")
    found = []
    if not root or workspace.get("kind") != "bind":
        found.append("the workspace is not a bind: a graded run reads and writes the reader's own sources "
                     "in place, and a copy is a second thing to keep in step")
    binds = [mount for mount in runner.get("mounts", []) if mount.get("kind") == "bind"]
    if len(binds) != 1:
        found.append(f"{len(binds)} binds are declared: the corpus's source root is mounted and nothing "
                     "else, not the repository and not $HOME")
    for mount in binds:
        path = mount.get("container_path", "")
        if path != root:
            found.append(f"the bind at {path} is not the workspace {root!r}: only the source root is mounted")
        if mount.get("must_exist_before_start") is not True:
            found.append(f"the bind at {path} does not say its source must exist before the container "
                         "starts; docker creates a missing one root-owned")
        if mount.get("read_only"):
            found.append(f"the bind at {path} is read-only: a graded run writes its build output there")
    return found


def _idle_findings(runner: dict) -> list[str]:
    """It idles on the image's own CMD, reaped, and is started detached."""
    found = []
    init = runner.get("init", {})
    if init.get("enabled") is not True or not init.get("run_flag"):
        found.append("init is not enabled: the container idles as pid 1 and reaps nothing, so a stopped "
                     "run leaves zombies behind")
    if runner.get("command"):
        found.append("the run line carries a command: it would replace the image's CMD, and the container "
                     "would exit before the first exec arrived")
    run = runner.get("run", {})
    if run.get("detached") is not True or not run.get("detach_flag"):
        found.append("the run is not detached: the reader starts this container and leaves it up")
    if not run.get("name_template") or not run.get("name_flag"):
        found.append("the run names no container, so nothing afterwards can exec into it")
    return found


def _environment_findings(runner: dict) -> list[str]:
    """A variable with no default is required, and one with a default is not."""
    found = []
    for entry in runner.get("environment", []):
        if entry.get("required") and entry.get("default") is not None:
            found.append(f"{entry.get('name')} is required and defaulted: a consumer cannot tell which "
                         "the image expects")
    return found


# ------------------------------------------------------------- the rendering
def run_line(runner: dict, *, name: str | None = None, source_root: str | None = None,
             tag: str | None = None, user: str | None = None, shell: str = POSIX) -> str:
    """The `docker run` line this block describes, or `Refused` naming the ruling it breaks.

    With no argument it renders the DOCUMENTED line, placeholders and all, which
    is what the README carries. With arguments it renders a real invocation.
    ⭐ `shell=POWERSHELL` writes `runs_as.powershell_run_value` where a POSIX shell
    would substitute the uid: every other word is the same in both shells.
    """
    _or_refuse(runner)
    if shell not in (POSIX, POWERSHELL):
        raise Refused(f"a run line is rendered for {POSIX} or {POWERSHELL}, not {shell!r}")
    run, runs_as = runner["run"], runner["runs_as"]
    if shell == POWERSHELL:
        runs_as = {**runs_as, "run_value": runs_as["powershell_run_value"]}
    parts = ["docker", "run"]
    if run["detached"]:
        parts.append(run["detach_flag"])
    parts += [run["name_flag"], name or run["name_template"]]
    parts.append(runner["init"]["run_flag"])
    parts += [runner["network"]["run_flag"], runner["network"]["mode"]]
    parts += [runs_as["run_flag"], _quoted(user or runs_as["run_value"], runs_as.get("quote_in_shell"))]
    for mount in runner["mounts"]:
        if mount["kind"] != "bind":
            continue
        source = source_root or mount["host_path"]
        suffix = ":ro" if mount["read_only"] else ""
        parts += ["-v", _quoted(f"{source}:{mount['container_path']}{suffix}", True)]
    parts.append(tag or runner["image"]["run_value"])
    return " ".join(parts)


def exec_line(runner: dict, *, name: str | None = None, directory: str | None = None,
              command: list[str] | None = None) -> str:
    """The `docker exec` line this block describes: a command run inside from outside."""
    _or_refuse(runner)
    root = runner["workspace"]["container_path"]
    filled = {"<name>": name or runner["run"]["name_template"]}
    if directory is not None:
        filled[f"{root}/<directory>"] = f"{root}/{directory}"
    parts = [filled.get(part, part) for part in runner["command_notes"]["exec_template"]]
    if command is not None:
        parts = parts[:-1] + list(command)
    return " ".join(parts)


def _or_refuse(runner: dict) -> None:
    broken = findings(runner)
    if broken:
        raise Refused("; ".join(broken))


def _quoted(value: str, quote: bool | None) -> str:
    """Double quotes, so `$(id -u)` is still substituted by a POSIX shell.

    ⭐ PowerShell reads double quotes the same way, and its value substitutes nothing.
    """
    return QUOTED.format(value) if quote else value
