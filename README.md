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
less, or one file that differs. ⛔ Warming a *corpus's* dependencies is not this
image's job.

Architectures: `linux/amd64` and `linux/arm64`. Any other is refused by name.

## Building

From this directory:

```sh
python3 docker/minimal/build.py --runtimes java,maven
python3 docker/minimal/build.py --runtimes java,maven --print-tag
```

The build refuses a name `pins.json` does not pin, and a build tool (`maven`,
`gradle`, `kotlin`) declared without `java`. The tag is

    code-server-toolchain/runner:<the sorted set>-<arch>-<12 hex of the inputs' sha256>

where the inputs are `pins.json` and everything under `docker/minimal/`.
Anyone with the same two inputs recomputes the same tag, so a report can name
the toolchain that produced a measurement.

`python3 docker/minimal/build.py --record-maven` re-derives the Maven warm list
into `.work/record/` for a person to review and copy into `pins.json`.

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
directory:

```sh
python3 docker/editor/build.py
python3 docker/editor/build.py --print-tag
```

- ⭐ **It chooses no runtime version.** The build first builds the runner for
  the editor's set (`gradle`, `java`, `kotlin`, `node`, `python`), then copies
  `/opt` and `/usr/local` out of it. `pins.json` stays the one place a runtime
  version is chosen.
- ⭐ **Its own pins live in [`editor-pins.json`](editor-pins.json)**: the
  code-server base (by index digest), each extension's `.vsix` (by sha256, per
  platform where the publisher builds per platform), TypeScript (by sha256),
  and the one Debian package the runner's Python needs on this base. Keeping them
  out of `pins.json` means an editor-only bump moves no runner tag.
- ⛔ **Extensions are installed with no network, from the pinned files only.**
  The build then requires the installed set to equal the pins exactly, and every
  declared extension dependency to be installed, or it fails naming the id.
  Removing a required extension's pin is refused before Docker starts.
- ⭐ `PATH` is set for `docker exec` and again in `/etc/profile.d`, and the
  build checks every toolchain's version under both `sh -c` and `bash -lc`.
  The settings seed declares the integrated terminal a login shell.

The tag is `code-server-toolchain/editor:<the set>-<arch>-<12 hex>`, and its
inputs are `editor-pins.json`, `docker/editor/` and the runner's own inputs.

⛔ **This section documents no way to run the editor.** How it is served (a
loopback port, mounts, the user) is the compose contract, which is a later task's.

## Tests

```sh
python3 -m unittest discover -s tests -v                   # the plans, pins and static checks
TC_DOCKER=1 python3 -m unittest tests.test_image -v        # builds and runs the runner
TC_DOCKER=1 python3 -m unittest tests.test_editor_image -v # builds and runs the editor
```

The image tests build a full image and a `shell`-only image, run every smoke
project under `docker/minimal/smoke/` with `--network none` (each passes, and a
planted failure fails), plant a wrong checksum, a wrong version and a changed
warm file in temporary copies (each stops the build), and exec into a container
started by the documented run line. They remove the images they build unless
`TC_KEEP_IMAGES=1`.
