# code-server-toolchain

The toolchain images the studyforge framework runs a corpus's code in. It is a
sibling repository of the framework, pinned by commit in the framework's
`workspace.json`. ⛔ It has no remote and is never pushed.

It holds two images: the **runner** (`docker/minimal/`), built by the
framework's task `TC-00`, and the browser **editor** (`docker/editor/`), added by
`TC-01`, which copies its toolchains out of the runner so they come from the same
pins.

## What the runner image is, and is not

- ⭐ **Exactly the runtimes one corpus declares, pinned, and nothing else.** A
  runtime that was not declared is *absent* from the image, not just off `PATH`.
- ⛔ **Not an editor.** No IDE, no extensions, no port. It is never served to a
  browser, and it must not grow into the editor image.
- ⛔ **No Docker socket is ever mounted into it**, and it carries no `docker`
  CLI. Whatever runs commands in it does so from outside, with `docker exec`.

## The pins — `pins.json`, the one place a version is chosen

Every runtime's version, and how it arrives, is written once in
[`pins.json`](pins.json). No `ARG` in the Dockerfile has a default, so the image
builds only through `docker/minimal/build.py`, which passes every value.

| runtime | arrives as | pinned by |
|---|---|---|
| base | Debian trixie-slim (Docker Official Image) | multi-arch index digest |
| `java` | Temurin 25 LTS JDK, copied out of the official image | multi-arch index digest |
| `maven` | the Apache binary tarball | sha256 recorded here; two hosts agree |
| `gradle` | the official distribution zip | sha256 recorded here; two hosts agree |
| `kotlin` | the JetBrains compiler zip | sha256 recorded here; **single-source** |
| `node` | the official tarball, per architecture | sha256 recorded here; **single-source** |
| `python` | the official Python image, used as the base | multi-arch index digest; pytest by `--require-hashes` |
| `sqlite` | Debian's package, from snapshot.debian.org | snapshot timestamp + exact version; apt checks the signed archive |
| `shell` | `bash`, from the base | the base's digest |

⛔ **The build fetches no checksum.** An archive is fetched with
`ADD --checksum=sha256:<recorded value>`, so a host that serves a different
file fails the build rather than agreeing with itself. Each pin records where
its value came from and when (`sources`), and whether a second, independent
source confirmed it (`single_source`).

⭐ **Maven's generic warm.** `mvn -o test` cannot run against an empty local
repository, so the image carries the plugins and JUnit that the Maven smoke
project needs, in `/opt/maven-repo`. Every file in it is listed in `pins.json`
with its sha256, and the build refuses a repository that holds one file more or
less, or one file that differs. ⛔ It warms the SMOKE project and nothing else:
a *corpus's* practice dependencies are `--prime`'s, below, and land in a tree
of their own, so this one keeps saying exactly what `pins.json` says.

Architectures: `linux/amd64` and `linux/arm64`. Any other is refused by name.

## Building

From this directory:

```sh
python3 docker/minimal/build.py --runtimes java,maven
python3 docker/minimal/build.py --runtimes java,maven --print-tag
python3 docker/minimal/build.py --runtimes java,maven --prime path/to/prime
```

The build refuses a name `pins.json` does not pin, and a build tool (`maven`,
`gradle`, `kotlin`) declared without `java`. The tag is

    code-server-toolchain/runner:<the sorted set>-<arch>-<12 hex of the inputs' sha256>

where the inputs are `pins.json` and everything under `docker/minimal/`, plus —
for a build given a `--prime` — that prime and the warmers in `prime/`, which
run only in such a build. Anyone with the same inputs recomputes the same tag,
so a report can name the toolchain that produced a measurement.

`python3 docker/minimal/build.py --record-maven` re-derives the Maven warm list
into `.work/record/` for a person to review and copy into `pins.json`.

### A corpus's practice dependencies — `--prime DIR`

⛔ **A reader's graded run happens in this image, under `--network none`**, so
whatever a corpus's practices depend on must already be inside it: a download
would not be slow, it would simply fail. `--prime DIR` warms them from that
corpus's own build files, exactly as the editor image warms a consumer's
(`TC-03`) — the contract, the version guards and the two warmers are
[`prime/`](prime/prime.py)'s, shared unchanged between the two images, and
`DIR` is mounted read-only as the named build context `consumer-prime`.

- ⭐ `DIR/gradle/` and `DIR/maven/`: the shape, the `verification-metadata.xml`
  Gradle needs and the version guards are the prime contract's, written once.
- ⭐ **The image is tagged only after the warm is PROVED**: a fresh copy of the
  prime builds with NO network from a copy of each seed.
- ⭐ **A graded run passes no cache flag of its own.** The seeds live at
  `/opt/prime/gradle-home` and `/opt/prime/maven-repo`, and the image points
  `GRADLE_USER_HOME` and `MAVEN_ARGS` at them, so `docker exec … gradle build
  --offline` and `docker exec … mvn -o test` resolve offline. They are left
  writable by any uid, because the run line below runs the container as the
  reader's own and both tools write into their cache.
- ⛔ **A corpus that declares none is unaffected**: no `--prime`, no warm, no
  `/opt/prime`, and the image is what it always was.
- ⛔ **The prime's digest is part of the tag**, so an image warmed for one
  corpus never wears another's name.

## Running it for a corpus

The **reader starts** the container, and the framework's runner only checks it
is up and runs commands inside it. If it is not up, the runner runs on the host
instead. Mount the corpus's **source root only**, at `/work`:

```sh
docker run -d --name studyforge-runner-<source> --init --network none \
  --user "$(id -u):$(id -g)" -v "<source root>:/work" <tag>
```

- `--network none`: nothing a build does inside it reaches off the machine.
- `--user`: files the build writes are owned by the reader, not by root.
- `--init`: the idle process is reaped, so a stop is prompt.
- No `-p`: nothing listens.

A command then runs inside it from outside:

```sh
docker exec -w /work/<directory> studyforge-runner-<source> <command...>
```

`PATH` is set for `docker exec` and again in `/etc/profile.d`, because a login
shell rebuilds `PATH` and would otherwise lose `/opt`. `HOME` is `/tmp`, so no
tool writes caches into the mounted sources.

## The editor image

`docker/editor/` builds code-server with the runner's toolchains, pinned
extensions, and a shell that finds every toolchain. Build it from this
directory, declaring the runtimes a corpus uses:

```sh
python3 docker/editor/build.py --runtimes java,maven
python3 docker/editor/build.py --runtimes java,maven --print-tag
python3 docker/editor/build.py            # gradle,java,kotlin,node,python
```

- ⭐ **The set is declared, and selected from `pins.json`.** `--runtimes` takes
  any of the runner's pinned runtimes (the runner's rules hold: `maven`,
  `gradle` and `kotlin` need `java`). With no `--runtimes`, the build makes the
  five-runtime image this component first shipped. A name `pins.json` does not
  pin is refused before Docker starts, naming it. ⚠️ `sqlite` is pinned for the
  runner but the editor cannot carry it (the runner installs it from Debian's
  packages into `/usr/bin`, and the editor copies only `/opt` and
  `/usr/local`), so selecting it is refused the same way.
- ⭐ **It chooses no runtime version.** The build first builds the runner for
  the declared set, then copies `/opt` and `/usr/local` out of it. `pins.json`
  stays the one place a runtime version is chosen.
- ⭐ **Its own pins live in [`editor-pins.json`](editor-pins.json)**: the
  code-server base (by index digest), each extension's `.vsix` (by sha256, per
  platform where the publisher builds per platform), TypeScript (by sha256),
  and the one Debian package the runner's Python needs on this base. Keeping them
  out of `pins.json` means an editor-only bump moves no runner tag.
- ⛔ **Extensions are installed with no network, from the pinned files only.**
  The build then requires the installed set to equal the pins exactly, and every
  declared extension dependency to be installed, or it fails naming the id.
  Removing a required extension's pin is refused before Docker starts.
- ⭐ **Nothing belongs to a runtime that is not declared.** Each extension
  names the runtime it serves (`for` in `editor-pins.json`), and only those
  for declared runtimes are installed; TypeScript comes with `node` and the
  readline package with `python`. `PATH` names only declared toolchains, and
  a set without `java` carries no `JAVA_HOME` at all. The settings seed's
  `java` and `python` blocks are dropped when their runtime is not declared.
- ⭐ `PATH` is set for `docker exec` and again in `/etc/profile.d`, and the
  build checks every declared toolchain's version under both `sh -c` and
  `bash -lc`, and keeps what each reported in
  `/opt/code-server/toolchain-versions`.
  The settings seed declares the integrated terminal a login shell.
- ⭐ **Every image carries the workbench lockdown**, whatever its set — it
  serves no runtime, so it is nothing a consumer selects (below).

The tag is `code-server-toolchain/editor:<the set>-<arch>-<12 hex>`, and its
inputs are `editor-pins.json`, `docker/editor/`, `prime/`, `lockdown/`, the
runner's own inputs and, when one is given, the prime directory. ⭐ **What a
tag promises, what forces a new one, and what to re-verify after re-pinning are
[`docs/consuming.md`](docs/consuming.md)'s section *Versioning and pinning*** —
in `consuming.json` under `editor.image.tag` for a generator.
⛔ **A tag is computed, never mutated and never hand-written:** a version bump
computes a new one instead of taking away the one somebody pinned.

### The workbench lockdown — `studyforge.practice-focus`

[`lockdown/`](lockdown/) is the practice-focus extension: it makes the embedded
IDE behave like a practice panel rather than a general workbench, by closing
every editor but the active one and every surface around it on startup, and
again whenever the practice changes. Plain CommonJS against the `vscode` module
the workbench provides — no build step, no dependencies, and nothing fetched.

- ⭐ **The id a consumer pins is `studyforge.practice-focus`.** It is written
  in one place, [`lockdown/package.json`](lockdown/package.json), and
  everything else derives from it: the `.vsix` file name, the manifest inside
  the zip, the build's expected-extension list and this line. A rename moves
  all of them at once, so a consumer pinning the documented id can never be
  reading a stale one.
- ⛔ **It is packaged and INSTALLED, never copied in.** The workbench reads
  `extensions.json` in its extensions directory and never scans it, so a copied
  folder is present, correct and silently never loaded. The build packs the
  `.vsix` with the standard library (`lockdown/lockdown.py`, never a
  marketplace tool), installs it with the pinned extensions, and then reads the
  INSTALLED list: an image whose lockdown did not load is not tagged.
- ⭐ **It reads no setting and knows no corpus.** Which file a window shows is
  decided by that window's own URL. It contributes
  `studyforge.practice.main` and `studyforge.practice.test` only so the
  workbench accepts the keys a study server writes, and treats a change to that
  section as the one signal that the practice moved.
- ⚠️ **It is not a security boundary.** code-server is an IDE with a shell;
  this removes the ways *in*, not the possibility. The boundary is the
  container and how it is run.

### The prime — the consumer's warm build cache

A reader's first offline build must need no download, and what it needs is
decided by the CONSUMER's build files. So a consumer supplies a **prime
directory** at build time, and the image warms its caches from it:

```sh
python3 docker/editor/build.py --runtimes gradle,java,maven --prime path/to/prime
```

**What a consumer supplies** (`prime/prime.py` is the contract's code):

| in the prime directory | what it is | warmed when |
|---|---|---|
| `gradle/` | a copy of the consumer's Gradle build files (settings, build scripts, wrapper if any) with one trivial source and test per project, and `gradle/verification-metadata.xml` recording a sha256 for every file it fetches | `gradle` is declared |
| `maven/` | a trivial module whose `pom.xml` reaches the consumer's parent POM, copied verbatim, by `relativePath`, with one trivial source and test | `maven` is declared |

Nothing else may sit at its top but plain files, and it must hold at least one
of the two. `tests/fixtures/prime/` is a placeholder of the shape, not any
consumer's project.

**Where it is mounted.** Read-only, as the build's named context
`consumer-prime`. It is never copied into the image; only what the warm
produced is.

- ⛔ **The sources must be real.** A compile task with no sources never
  resolves its classpath, so an empty prime would prime nothing while
  appearing to succeed. Every Gradle project that compiles must run a main
  compile, a test compile and `test`; every Maven module must compile
  sources and run a test. Otherwise the build fails, naming the project.
- ⛔ **Versions must agree with `pins.json`, or the build is refused before
  Docker starts**, naming the file and both versions: a Gradle or Maven
  wrapper naming another version (and a Gradle wrapper that does not pin the
  pinned distribution's sha256), a Kotlin plugin other than the pinned
  Kotlin, a Gradle toolchain other than the pinned JDK (an offline build
  cannot provision one), or a Maven release newer than the pinned JDK. A
  cache warmed for another version misses in ways nobody looks for.
- ⭐ **Maven warms what the POM declares**, not what the tests use: running
  the `test` phase resolves every declared dependency of every module. There
  is no Maven wrapper to follow, so the image's pinned Maven is the version.
  Each file is checked against Maven Central's own checksum as it arrives.
- ⭐ A project directory whose tool is not declared is refused, naming it.

**What the image guarantees.** Built with a prime, it holds a Gradle user home
at `/opt/code-server/prime/gradle-home` and a Maven repository at
`/opt/code-server/prime/maven-repo`, and it was tagged only after a fresh
copy of the prime built with NO network from a copy of each (`gradle build
--offline`, `mvn -o test`). On start, the entrypoint copies each to where the
tool looks (`$GRADLE_USER_HOME`, default `~/.gradle`, and
`~/.m2/repository`) when that directory is empty, and never touches one that
is not. So a reader's first `gradle build --offline` and `mvn -o test` of a
project built from the same files need no network. The prime's digest is part
of the tag.

### The compose and mount contract — how a consumer SERVES the editor

The image is shared; the compose file and its mounts are not. What a consuming
project must provide, and the rulings it must not break, are in
[`docs/consuming.md`](docs/consuming.md) for a person and in
[`consuming.json`](consuming.json) for a generator — ⛔ **a consumer reads those
and never this repository's `Dockerfile`.**

[`docs/compose.reference.yaml`](docs/compose.reference.yaml) is a complete,
working compose file, ⛔ **a template to copy and adapt, never an `include:`**:
the mount list is exactly the part that must differ per project. It is
**generated** from `consuming.json` and nothing else, so the contract and the
template cannot drift.

```sh
python3 consuming/consuming.py --check    # the rulings, on the real contract
python3 consuming/consuming.py --write docs/compose.reference.yaml
```

The five rulings a consumer inherits, each with the failure that bought it, are
loopback-only publishing, the sources and nothing else, the repository owner's
uid:gid, a bind source that exists on the host before the container starts, and
a writable root filesystem — the entrypoint repairs the passwd record at every
start and the primed caches are written under `/opt`, so a read-only root breaks
the editor at start and every graded run in it.
⛔ **No Docker socket is mounted into the editor, or anywhere else** (spec
§8.3): it is an IDE with a shell on a port.

## Tests

```sh
python3 -m unittest discover -s tests -v                   # the plans, pins and static checks
TC_DOCKER=1 python3 -m unittest tests.test_image -v        # builds and runs the runner
TC_DOCKER=1 python3 -m unittest tests.test_editor_image -v # builds and runs the editor
TC_DOCKER=1 python3 -m unittest tests.test_editor_selection_image -v # the selected sets
TC_DOCKER=1 python3 -m unittest tests.test_prime_image -v   # the prime, warm and offline
TC_DOCKER=1 python3 -m unittest tests.test_runner_prime_image -v # a graded run, offline
TC_DOCKER=1 python3 -m unittest tests.test_consuming_image -v # the compose contract, brought up
```

`tests/test_lockdown.py` needs no Docker: it packs the extension with the
standard library, runs it against a stub `vscode` module with `node`, and
reads the packed identity against this README and the build's expected list.
`tests/test_consuming.py` needs none either: it reads every value
`consuming.json` states about the image back out of the build's own plan, the
Dockerfile and the lockdown manifest, resolves every key `docs/consuming.md`
names, and plants a violation of each ruling to see it refused.

`tests/test_consuming_image.py` copies `docs/compose.reference.yaml` VERBATIM
into an empty directory, supplies only what that file asks for by name, and
brings it up: the editor answers its health path on loopback and nowhere else,
a file it writes into the mounted sources belongs to the host user, a uid that
is not the image's own starts (and the same image without its entrypoint's
`fixuid` does not), a missing bind source is created root-owned and cannot be
written, a read-only root filesystem never starts at all, and no Docker socket
is anywhere near it. It also builds a SECOND image from a second declared set
and brings it up beside the first, on its own port: two consumers holding two
tags, both healthy at once.

The image tests build a full image and a `shell`-only image, run every smoke
project under `docker/minimal/smoke/` with `--network none` (each passes, and a
planted failure fails), plant a wrong checksum, a wrong version and a changed
warm file in temporary copies (each stops the build), and exec into a container
started by the documented run line. They remove the images they build unless
`TC_KEEP_IMAGES=1`.
