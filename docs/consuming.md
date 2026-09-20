# Consuming the editor image — the compose and mount contract

This is what a project must provide to serve the editor image
(`editor.what_it_is`), and the rulings it must not break. ⛔ **It is the
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
its checkout and pins the tag the build prints. What that tag promises is the
next section.

## Versioning and pinning — what a tag promises

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

## The five rulings a consumer inherits

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

⚠️ **This is not an argument for mounting anything else.** Ruling 2 still holds:
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
