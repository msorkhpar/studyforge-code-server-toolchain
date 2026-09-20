# Consuming this component's images — the compose and mount contract

This is what a project must provide to serve the editor image
(`editor.what_it_is`) and to run the runner image (`runner.what_it_is`),
and the rulings it must not break. ⭐ **The editor has a compose file and
the runner does not** — a reader starts one runner container by hand — so
everything up to [The runner image](#the-runner-image) is the editor's, and
that last section is the runner's whole half. ⛔ **It is the
consumer-side half of the seam: the image is shared, the compose file and its
mounts are not.**

⭐ **Everything below is READ OUT of [`consuming.json`](../consuming.json), this
component's machine-readable contract.** This document quotes it and does not
restate it, because two copies of a contract drift and only one of them is
checked. ⛔ **A consumer never reads the `Dockerfile`** — if something you need
is not in `consuming.json`, that is a hole in this contract and a finding
against this component, not a reason to open the image's source.

## The reference fragment is a TEMPLATE, not an include

[`compose.reference.yaml`](compose.reference.yaml) is a complete, working
compose file. ⛔ **Copy it into your own repository and adapt it. Never
`include:` it and never reference it from another project**: the mount list is
exactly the part that must differ per project, so a shared file would be wrong
for every consumer at once.

It is **generated** from `consuming.json` by `consuming/consuming.py`, with no
other input, and a test asserts the checked-in file is what the contract renders
today. So an edit to this component's contract moves the template; an edit to
the template moves nothing and is a finding (R19).

```sh
python3 consuming/consuming.py --check                        # the rulings, on the real contract
python3 consuming/consuming.py --write docs/compose.reference.yaml
```

## What you supply

| you supply | the contract's key | the reference's value |
|---|---|---|
| the image tag you pinned | `editor.image.env_var` | `EDITOR_IMAGE`, built and printed by `editor.image.tag_from` |
| the password | `editor.environment[0].name` | `CODE_SERVER_PASSWORD`, with no default |
| the host port | `editor.ports[0].host` | `8443`, bound to `editor.ports[0].host_bind` |
| the owner's uid:gid | `editor.runs_as.compose_value` | `${HOST_UID:-1000}:${HOST_GID:-1000}` |
| your source paths | `editor.mounts[0].host_path` | `./sources`, at `editor.mounts[0].container_path` |
| the project name | compose's `name:` | `studyforge-editor` |

Everything else — the toolchains, the extensions, the workbench lockdown, the
seed settings, the entrypoint — comes from the image.

**The runtimes** are chosen when the image is BUILT, not when it is run:
`editor.runtimes.declared_by` is `--runtimes`, `editor.runtimes.default_set` is
what a build with no flag makes, `editor.runtimes.selectable` is everything
`pins.json` offers the editor, and `editor.runtimes.not_carried` says which
pinned runtime the editor cannot carry and why. A built image states its own set
in the label `editor.runtimes.read_back_from`.

**The image has no registry** (`editor.image.registry` is `null`): this
component has no remote and is never pushed, so a consumer builds the image from
its checkout and pins the tag the build prints. ⚠️ What a tag *promises* — what
may change inside one and what forces a new one — is not in this file yet; it is
named in `not_yet_declared` and belongs to the versioning task.

## The four rulings a consumer inherits

Each of these was paid for once. The failure is written beside it so nobody
re-derives it, and `consuming/consuming.py`'s `findings()` refuses a contract
that breaks any of them rather than rendering a compose file that does.

### 1. Loopback-only port binding, never `0.0.0.0`

`editor.ports[0].host_bind` is `127.0.0.1` and
`editor.ports[0].publish_on_all_interfaces` is `false`.

⛔ **The failure: this is an unencrypted IDE with a shell.** Published on
`0.0.0.0` it is offered to every machine that can reach the host, with no TLS
and a terminal behind it. `editor.ports[0].why` says it in one line.

⚠️ **`--bind-addr=0.0.0.0:8080` in `editor.command` is not a contradiction**, and
`editor.command_notes.bind_addr` is the reason: that is the *container's* own
interface, which is the only one the process can answer on. The loopback
restriction is the host publish, and nothing else.

### 2. Mount only the sources — not the repository, not `$HOME`

Every bind in `editor.mounts` sits strictly inside `editor.workspace.container_path`,
and `findings()` reports one that does not.

⛔ **The failure: the editor is a shell.** A repository mount hands it the git
history, the pipeline, the generated site and every credential that happens to
be in the tree; a `$HOME` mount hands it the reader's whole machine. Mount the
directories a reader edits, and nothing else.

⚠️ **The workspace root itself is a `tmpfs`** (`editor.workspace.kind`), and
`editor.workspace.why` is the measured reason: that directory is not in the
image, so docker would create it root-owned and no build could write `.gradle/`,
`.kotlin/` or `build/` into it. A named volume there is root-owned for the same
reason. The source binds sit inside the tmpfs.

### 3. Run as the repository owner's uid:gid

`editor.runs_as.compose_value` goes under `editor.runs_as.compose_key`. The
image's own user is `editor.runs_as.uid`:`editor.runs_as.gid`
(`editor.runs_as.user`), and `editor.runs_as.set_to` says what to replace it
with.

⛔ **The failure: files created in the container are root-owned on the host**,
and the reader can then never edit their own repository without `sudo`.

⭐ **A uid other than the image's own works**, and `editor.runs_as.how` says how:
the base image's `fixuid` repairs the passwd record and the ownership of the home
directory at start, and the editor's entrypoint runs it **before** it seeds
anything. ⚠️ Without that ordering the seed step ran with `HOME=/` and the
container exited before code-server started — measured, and the reason the
entrypoint runs `fixuid` itself.

### 4. A bind source must exist on the host before the container starts

Every bind in `editor.mounts` carries `must_exist_before_start`, and `findings()`
reports one that does not.

⛔ **The failure: docker creates a missing bind source itself, root-owned**, and
the writer can then never write it. The mount succeeds, the container starts,
and the failure surfaces later as a permission error nobody connects to the
compose file.

⭐ **Ordering is enforced by a health check, not by hope.**
`editor.healthcheck.ordering` is the shape: where another service in your
project creates one of these directories, gate the editor on it with
`depends_on: <that service>: condition: service_healthy`, so the editor starts
only after the directory exists. Where you create it yourself, create it before
`docker compose up`.

## The restart policy

`editor.restart` is `"no"`, and `editor.why_restart_no` is the reason: an IDE
with a shell comes up when the reader asks for it, not on every boot. ⚠️ A
reading surface that a reader opens every day is a different judgement — make
that one `unless-stopped` in your own project, and leave this one alone.

## The health check

`editor.healthcheck.path` answers `editor.healthcheck.expect_status` when the
editor is serving, and it needs no authentication.
`editor.healthcheck.command` is the exact `test:` line, and
`editor.healthcheck.why_this_interpreter` is why it runs code-server's own node:
a set without `python` has no `python3`, and a set without `node` has none on
`PATH`, so neither is safe to reach for.

## ⛔ No Docker socket. Anywhere.

`editor.docker_socket` is `false` and `editor.why_no_docker_socket` is the
ruling: spec §8.3, not behind a flag and not "only locally". A socket inside a
process that listens on a port is root-equivalent access to the host, and this
process is an IDE with a shell. `findings()` refuses a contract that says
otherwise and refuses a mount that names the socket.

## What the image brings, so your compose file does not

- **The extensions** are installed into the image at `editor.extensions.installed_at`,
  never onto a volume, so an image upgrade always carries them. Nothing in a
  compose file selects them.
- **The workbench lockdown** is in `editor.extensions.always_installed`: every
  image installs it, whatever its set. The two settings a study server writes
  into the workspace are `editor.extensions.settings_a_study_server_writes`.
- **The seed settings and the primed caches** are written by the entrypoint on
  first start, into the volumes at `/home/coder/.local`, `/home/coder/.gradle`
  and `/home/coder/.m2` — and never over a reader's own. To get the seed again,
  remove the volume.
- **`ENTRYPOINT` and `CMD` are both re-declared** by the image
  (`editor.command_notes.replaces_cmd`), so a compose `command:` replaces the
  whole command line instead of being appended to arguments the base baked in.

## Bringing it up

From the directory holding your copy of the template:

```sh
mkdir -p sources                              # ruling 4: before the container starts
export EDITOR_IMAGE="$(python3 docker/editor/build.py --runtimes java,maven --print-tag)"
export CODE_SERVER_PASSWORD=...               # ruling: never unauthenticated
export HOST_UID="$(id -u)" HOST_GID="$(id -g)"
docker compose up -d --wait
```

The editor is then at `http://127.0.0.1:8443/` — that literal host, and no
other. `docker compose down -v` removes the containers and the volumes with
them.

## The runner image

A reader's **graded run** happens in the runner image, not in the editor: the
editor is where they read and type, the runner is where their code is compiled
and their tests are run, offline. ⛔ **The framework never starts one**
(`runner.started_by`) — it probes that the reader's container is up, execs into
it, and runs on the host when it is not.

⚠️ **There is no compose file here and that is deliberate.** One container, one
bind, no port and no second service is a `docker run` line, and a compose
project would add a file for a consumer to keep in step for nothing. So the
runner's half of this contract is the `runner` block and the two command lines
rendered from it:

```sh
python3 consuming/consuming.py --run-line   # exactly the line below
```

```sh
docker run -d --name studyforge-runner-<source> --init --network none \
  --user "$(id -u):$(id -g)" -v "<source root>:/work" <tag>
```

⭐ **That line is GENERATED from the block and a test asserts the one in
[`../README.md`](../README.md) is what it renders** (`runner.run.why_rendered`),
so the prose a consumer copies and the data a generator reads cannot drift
apart. A command then runs inside it from outside, from
`runner.command_notes.exec_template`.

### What you supply

- **The image**, built from this checkout and pinned by the tag the build
  prints (`runner.image.tag_from`, `runner.image.repository`, and
  `runner.image.registry`, which is `null` for the same reason the editor's is).
  The framework's own tests name it in `runner.image.env_var`. The set a corpus
  declares comes from `runner.runtimes.selectable`; there is no default set and
  `runner.runtimes.why_no_default` says why.
- **The source root**, at `runner.workspace.container_path`. It is the one bind
  (`runner.mounts`), it must exist before the container starts, and
  `runner.workspace.why` is why it is a bind here and a tmpfs in the editor.
- **The uid:gid that owns it**, as `runner.runs_as.run_value`. ⛔ This image
  declares no `USER` (`runner.runs_as.why`), so a run without the flag is root
  and every file a graded run writes into the reader's sources is root's.
  ⚠️ Write it in **double** quotes: `runner.runs_as.quote_in_shell` is true
  because a shell must still substitute it.
- **No environment of your own.** `runner.environment` is what the IMAGE sets
  and a consumer does not: `HOME` is outside the mount, so no tool writes its
  caches into the reader's sources, and a primed image sets each tool's cache
  variable to the seed the warmer wrote.
- **Nothing else.** `runner.command` is empty on purpose
  (`runner.command_notes.keeps_cmd`): the image's own `CMD` idles it, and a
  command on the run line would replace that and exit before the first exec
  arrived.

### The rulings this block carries

- ⛔ **Offline.** `runner.network.mode` is `none`
  (`runner.network.why`): a practice must not pass because the reader happened
  to be online. What a corpus's practices need is warmed into the image instead
  — `runner.prime` names where the seeds land and that the prime's digest is
  folded into the tag.
- ⛔ **Nothing listens.** `runner.ports` is empty and `runner.why_no_ports` is
  why; `runner.healthcheck` is `null` and `runner.why_no_healthcheck` says what
  a consumer does instead of waiting on one.
- ⛔ **The owner's uid:gid**, above — the editor's ruling 3, in an image with no
  `fixuid` and none needed (`runner.runs_as.how`).
- ⛔ **A bind source that exists first**, above — the editor's ruling 4, and
  docker creates a missing one root-owned here exactly as it does there.
- ⛔ **No Docker socket.** `runner.docker_socket` is `false` and
  `runner.why_no_docker_socket` is the reason, which is sharper here than for
  the editor: a graded run is a reader's unreviewed code.
- ⭐ **Reaped and detached.** `runner.init` and `runner.run`: the container
  idles on `sleep infinity` as pid 1, so without an init a stop is slow and
  leaves zombies.

⛔ **`runner.restart` is `"no"`** (`runner.why_restart_no`): a restart policy
would bring a stranger's sources back up on every boot.
