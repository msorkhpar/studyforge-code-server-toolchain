# code-server-toolchain

The toolchain images the studyforge framework runs a corpus's code in. It is a
sibling repository of the framework, pinned by commit in the framework's
`workspace.json`. ⛔ It has no remote and is never pushed.

Today it holds one image, the **runner** (`docker/minimal/`), built by the
framework's task `TC-00`. The browser editor image (`TC-01` onward) is added
here later and **selects** its toolchains from the same pins.

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

## Tests

```sh
python3 -m unittest discover -s tests -v            # the plan, pins and static checks
TC_DOCKER=1 python3 -m unittest tests.test_image -v # builds and runs the image
```

The image tests build a full image and a `shell`-only image, run every smoke
project under `docker/minimal/smoke/` with `--network none` (each passes, and a
planted failure fails), plant a wrong checksum, a wrong version and a changed
warm file in temporary copies (each stops the build), and exec into a container
started by the documented run line. They remove the images they build unless
`TC_KEEP_IMAGES=1`.
