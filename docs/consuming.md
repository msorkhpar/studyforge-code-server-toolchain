# Consuming this component's images — the compose and mount contract

This is what a project must provide to serve the editor image
(`editor.what_it_is`) and to run the runner image (`runner.what_it_is`),
and the rules it must not break. ⭐ **The editor has a compose file and
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
the template moves nothing and is a finding: the next render writes over it.

```sh
python3 consuming/consuming.py --check                        # the rules, on the real contract
python3 consuming/consuming.py --write docs/compose.reference.yaml
```

## What you supply

| you supply | the contract's key | the reference's value |
|---|---|---|
| the image tag you pinned | `editor.image.env_var` | `EDITOR_IMAGE`, built and printed by `editor.image.tag_from` |
| the auth mode | `editor.command[0]` | `--auth=none`, and only because the port is loopback-bound |
| the host port | `editor.ports[0].host` | `8443`, bound to `editor.ports[0].host_bind` |
| the owner's uid:gid | `editor.runs_as.compose_value` | `${HOST_UID:-1000}:${HOST_GID:-1000}` |
| your source paths | `editor.mounts[0].host_path` | `./sources`, at `editor.mounts[0].container_path` |
| the project name | compose's `name:` | `studyforge-editor` |

Everything else — the toolchains, the extensions, the workbench lockdown, the
seed settings, the entrypoint — comes from the image.

⭐ **You supply no environment at all.** `editor.environment` carries one entry,
`GRADLE_USER_HOME`, and it has a default; the reference compose writes it
explicitly so the seeded cache and the tool agree on one path. ⚠️ **It used to
carry a second, `PASSWORD`, which you did have to supply** — that is gone with
the auth mode.

**The runtimes** are chosen when the image is BUILT, not when it is run:
`editor.runtimes.declared_by` is `--runtimes`, `editor.runtimes.default_set` is
what a build with no flag makes, `editor.runtimes.selectable` is everything
`pins.json` offers the editor, and `editor.runtimes.not_carried` says which
pinned runtime the editor cannot carry and why. A built image states its own set
in the label `editor.runtimes.read_back_from`.

**The prime** is chosen when the image is BUILT too, exactly as the runner's
is: `editor.prime.declared_by` is the flag its build takes, pointing at your
corpus's prime directory, `editor.prime.root` and `editor.prime.seeds` say where
the warmed caches land, and `editor.prime.folded_into_tag` is `true`, so a
primed editor's tag names the prime it was warmed with. Hand the editor's build
and its `editor.image.tag_from` the same prime you hand the runner's, and record
the tag that primed command prints.

**Two ways to get the image.** Build it from a checkout and pin the tag the
build prints, or pull one that its publisher pushed. `editor.image.registry`
names the second path by variable: the namespace is read from
`TOOLCHAIN_NAMESPACE`, never written in this repository, and the reference is
`${TOOLCHAIN_NAMESPACE}/editor:<tag>`. The publisher runs
`python3 docker/publish.py editor --runtimes <the declared set> --dry-run` to
see the exact commands, then the same line with `--push` after logging in
themselves; the script never logs in and pushes only with that flag. ⭐ **A
consumer that pulls pins the DIGEST** that `docker push` prints, because a tag
in a registry can be moved and a digest cannot. What a tag promises is the next
section.

## Versioning and pinning — what a tag promises

⭐ **Both images this component builds use the same scheme**, and each block
states it for itself: `editor.image.tag` and `runner.image.tag`. This section is
written in the editor's keys; every sentence in it is true of the runner's with
the names swapped, and the one place they differ — which inputs the digest reads
— has a subsection of its own under *The runner image* below.

⭐ **A tag is a function of the build's inputs, and that is the whole of its
promise.** `editor.image.tag.scheme` is its shape and
`editor.image.tag.parts` says what each part is:

| part | what it is |
|---|---|
| repository | `editor.image.repository` — one editor image, named once |
| set | `editor.image.tag.parts.set` |
| arch | `editor.image.tag.parts.arch` |
| inputs | `editor.image.tag.parts.inputs`, over `editor.image.tag.build_inputs` |

`editor.image.tag.example` is one: `code-server-toolchain/editor:java-maven-amd64-0123456789ab`.

⛔ **Never parse a tag.** The set is joined with hyphens, so it cannot be split
back out unambiguously — `editor.image.tag.computed_not_parsed`. Ask the build
for the tag, and read the set back off the image you pinned, from the label
`editor.runtimes.read_back_from`.

### What forces a new tag, and what does not

`editor.image.tag.moved_by` is the list. In one line: **the declared set, the
architecture, and any byte under `editor.image.tag.build_inputs`** — which is
every pin file, the Dockerfiles, the entrypoint, the prime warmers and the
lockdown extension, and the prime directory's own digest when one is supplied.
⭐ **So a toolchain version bump computes a NEW tag; it cannot mutate the one you
pinned.** `editor.image.tag.mutated_in_place` is `false` and
`editor.image.tag.why_it_cannot_be` says why: a changed input computes a
different name, so no later build can take away a name a consumer is holding.

`editor.image.tag.not_moved_by` is the other half, and it is the one that
surprises people: **this contract, its document, its renderer and the tests move
without moving any tag.** They are versioned by `provides`, which a tag does not
encode. ⛔ **Read both**: the tag for the image, `provides` for what you may read
out of this file.

⭐ **The two images do not move together, and that is deliberate.** The editor is
built ON the runner, so it folds the runner's digest into its own and adds four
roots of its own (`editor.image.tag.build_inputs`). The runner knows nothing
about the editor (`runner.image.tag.build_inputs` is two roots), so
`runner.image.tag.not_moved_by` names the editor's inputs explicitly: **an
editor-only change moves no runner tag.** A consumer that pins only the runner is
not dragged along by the editor's releases.

`editor.image.tag.promises` and `editor.image.tag.does_not_promise` are exact.
⚠️ **The one a consumer most often assumes is in the second list:** two hosts
that build the same tag ran the same pinned inputs, **not** the same bytes. A
Docker build is not bit-reproducible and this component does not claim it is.

### Two consumers, two tags, at once

⭐ **Nothing serialises them.** Two projects that declare different sets compute
different tags, build them and run them side by side; the compose file's
`name:`, its volumes and `editor.ports[0].host` are all per-project, so the two
containers share nothing. Two projects on two *checkouts* of this component do
the same, because the checkout is an input.

```sh
# consumer A, in its own repository, pinned at this component's commit
export EDITOR_IMAGE="$(python3 docker/editor/build.py --runtimes java,maven --print-tag)"
# consumer B, which also wants Gradle — a different set, so a different tag
export EDITOR_IMAGE="$(python3 docker/editor/build.py --runtimes gradle,java --print-tag)"
```

The same in PowerShell on Windows:

```powershell
$env:EDITOR_IMAGE = (python docker/editor/build.py --runtimes java,maven --print-tag)
$env:EDITOR_IMAGE = (python docker/editor/build.py --runtimes gradle,java --print-tag)
```

### Upgrading

`editor.image.tag.upgrade.how`: re-run `editor.image.tag.computed_by` in the new
checkout and compare it with the tag you hold. When it differs, rebuild, re-pin,
and work `editor.image.tag.upgrade.re_verify` — the set off the label, `provides`
in this file, a health check that answers, and a file the container writes into
your sources that belongs to you.

⭐ **Per release there is a short note saying what to re-verify**, in this file's
top-level `releases` array, newest first
(`editor.image.tag.upgrade.notes_per_release`). Each entry carries its
`provides`, a summary, and **whether it moved every tag** — because a change to
the image and a change to this contract are different events and a consumer acts
on them differently. `consuming/consuming.py` refuses a `provides` bump that
arrives with no entry.

## The five rules a consumer inherits

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

⭐ **Every bind source is the project's own directory, written relative to the
compose file** (`./sources`), and everything else is a named volume or a
`tmpfs`. ⛔ Never a host temporary directory and never an absolute host path
written at build time: the compose file must run on
any engine, Docker Desktop (which shares no host `/tmp`) and Windows (which has
none) included, and a relative bind is the one form Compose resolves on both.

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

### 5. The root filesystem stays writable

`editor.filesystem.read_only_root` is `false`, `editor.filesystem.compose_key`
is what carries it into your file, and `editor.filesystem.never_read_only` names
the paths a mount must never make read-only.

⛔ **The failure: the image writes outside its mounts, and a read-only root stops
it twice over.** The entrypoint's `fixuid` repairs the passwd record at every
start, which writes under `/etc`; and the warmed practice caches live under
`/opt`, where Gradle and Maven write on every build — so a container with a
read-only root filesystem either never starts or fails every graded run in it.
`editor.filesystem.why` is the line, and `findings()` reports a contract that
declares the root read-only and a mount that makes one of those paths read-only.

⚠️ **This is not an argument for mounting anything else.** Rule 2 still holds:
writable does not mean shared. `editor.filesystem.what_is_discarded_with_the_container`
says what happens to those writes — everything outside `editor.mounts` goes with
the container.

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
rule: never, not behind a flag and not "only locally". A socket inside a
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
mkdir -p sources                              # rule 4: before the container starts
export EDITOR_IMAGE="$(python3 docker/editor/build.py --runtimes java,maven --print-tag)"
export HOST_UID="$(id -u)" HOST_GID="$(id -g)"
docker compose up -d --wait
```

In PowerShell on Windows, where a user has no uid, `HOST_UID` and `HOST_GID` are
left unset and the compose value's default, an ordinary user, runs the editor;
Docker Desktop hands the files it writes into `sources` to the Windows user:

```powershell
New-Item -ItemType Directory -Force sources | Out-Null   # rule 4
$env:EDITOR_IMAGE = (python docker/editor/build.py --runtimes java,maven --print-tag)
docker compose up -d --wait
```

The editor is then at `http://127.0.0.1:8443/` — that literal host, and no
other. ⛔ **It asks for no password** (`editor.command_notes.auth`): loopback is the whole of its access control, so publishing this
port anywhere but `127.0.0.1` puts an unauthenticated shell on the network. `docker compose down -v` removes the containers and the volumes with
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

In PowerShell (`--run-line --powershell`), from `runner.runs_as.powershell_run_value`:

```powershell
docker run -d --name studyforge-runner-<source> --init --network none `
  --user "1000:1000" -v "<source root>:/work" <tag>
```

⭐ A consumer rendering the runner as a compose service takes
`runner.runs_as.compose_key` and `compose_value`, which compose interpolates on
every host, and never the shell's `run_value`.

⭐ **That line is GENERATED from the block and a test asserts the one in
[`../README.md`](../README.md) is what it renders** (`runner.run.why_rendered`),
so the prose a consumer copies and the data a generator reads cannot drift
apart. A command then runs inside it from outside, from
`runner.command_notes.exec_template`.

### What you supply

- **The image**, built from this checkout and pinned by the tag the build
  prints (`runner.image.tag_from`, `runner.image.repository`, and
  `runner.image.registry`, the same two paths as the editor's).
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

### The rules this block carries

- ⛔ **Offline.** `runner.network.mode` is `none`
  (`runner.network.why`): a practice must not pass because the reader happened
  to be online. What a corpus's practices need is warmed into the image instead
  — `runner.prime` names where the seeds land and that the prime's digest is
  folded into the tag.
- ⛔ **Nothing listens.** `runner.ports` is empty and `runner.why_no_ports` is
  why; `runner.healthcheck` is `null` and `runner.why_no_healthcheck` says what
  a consumer does instead of waiting on one.
- ⛔ **The owner's uid:gid**, above — the editor's rule 3, in an image with no
  `fixuid` and none needed (`runner.runs_as.how`).
- ⛔ **A bind source that exists first**, above — the editor's rule 4, and
  docker creates a missing one root-owned here exactly as it does there.
- ⛔ **No Docker socket.** `runner.docker_socket` is `false` and
  `runner.why_no_docker_socket` is the reason, which is sharper here than for
  the editor: a graded run is a reader's unreviewed code.
- ⭐ **Reaped and detached.** `runner.init` and `runner.run`: the container
  idles on `sleep infinity` as pid 1, so without an init a stop is slow and
  leaves zombies.

⛔ **`runner.restart` is `"no"`** (`runner.why_restart_no`): a restart policy
would bring a stranger's sources back up on every boot.

### What the runner's tag promises

`runner.image.tag` is the same scheme as the editor's, stated in the runner's own
keys: `runner.image.tag.scheme`, `runner.image.tag.parts`, and
`runner.image.tag.computed_by` for the command that prints one.
`runner.image.tag.example` is one:
`code-server-toolchain/runner:java-maven-amd64-0123456789ab`.

⭐ **The one real difference is which inputs the digest reads.**
`runner.image.tag.build_inputs` is two roots — `pins.json` and
`docker/minimal/` — against the editor's six, and
`runner.image.tag.why_fewer_inputs_than_the_editor` is the reason: the editor is
built on the runner and folds its digest in, while the runner knows nothing about
the editor. ⛔ **So an editor-only change moves no runner tag**, which
`runner.image.tag.not_moved_by` states in as many words.

⚠️ **`prime/` is NOT in `runner.image.tag.build_inputs`, and
`runner.prime.folded_into_tag` is still `true`** — both are correct. The warmers
run only in a build given `--prime`, so that build folds `prime/` and the prime
directory into its own digest. An unprimed runner tag therefore does not move
when a warmer changes, and a primed one names the corpus it was warmed for.
`runner.image.tag.moved_by`'s last entry says exactly this.

`runner.image.tag.promises`, `runner.image.tag.does_not_promise`,
`runner.image.tag.mutated_in_place` and `runner.image.tag.how_to_pin` read as the
editor's do, and `runner.image.tag.upgrade.re_verify` is the runner's own
checklist: the set off the label, `provides` in this file, a `docker exec` of a
practice's command that exits zero with no network, and a file the run wrote into
your source root that belongs to you.

## Building with compose, and one course layer per consumer

⭐ **`python3 consuming/builds.py <image> --runtimes <set>` prints a build as
data** (`builds.printed_by`, shaped by `builds.keys` and versioned by
`builds.builds_api`): the Dockerfile, the target, every ARG, the named contexts,
the images it starts FROM, which of those this component builds itself, the tag
and the input roots the context must carry. ⛔ A consumer that writes a compose
`build:` block renders it from this and never from a Dockerfile, which is the
rule this document opened with: the ARGs are the plans' own, so a compose build
makes the image `build.py` makes, under the tag `--print-tag` prints.

⚠️ **What a compose build does not do** is the editor's two session proofs,
which `docker/editor/build.py` runs between the build and the tag with a
browser. `builds.not_proved_by_a_compose_build` says so, and the editor's
document names both commands in its `proved_by`: a consumer that PUBLISHES an
editor it built with compose runs both against that image first.

⭐ **A course layer** (`course_layer.dockerfile`, `docker/prime/Dockerfile`)
warms one consumer's prime on top of the UNPRIMED runner or editor for its
declared set, where a primed build (`--prime`) makes a whole image per
consumer. So every consumer of one set shares one runner and one editor, and
each carries only its own caches. `course_layer.same_as_a_primed_build` holds it
to the primed images' own warm, proof and seed roots
(`course_layer.prime_roots`); its tag is `course_layer.tag.scheme`, the base's
tag with the layer's own digest after it.
