# studyforge-code-server-toolchain

The toolchain images the studyforge framework runs a corpus's code in. It is a
sibling repository of the framework (the `studyforge` repository), pinned by
commit in the framework's `workspace.json`. Images are built from a checkout;
publishing one to a registry is optional (*Publishing an image*, below).

Get it, next to the framework's checkout:

```sh
git clone https://github.com/msorkhpar/studyforge-code-server-toolchain.git
```

The framework itself is at `https://github.com/msorkhpar/studyforge.git`.

It holds two images: the **runner** (`docker/minimal/`), where a reader's code
is built and graded, and the browser **editor** (`docker/editor/`), which copies
its toolchains out of the runner so they come from the same pins.

## Reading list

Read in this order; nothing outside this repository is needed.

1. **This README**: what each image is, how to build it locally by tag, and how
   to run this repository's own suite (*Building*, *The editor image*, *Tests*).
2. **[`consuming.json`](consuming.json)**: the machine-readable contract, one
   block per image (`runner`, `editor`). It states each image's repository, how
   its tag is computed and what a tag promises, the run shape or compose shape,
   mounts, uid, ports and their loopback binding. ⛔ **A consumer reads this, not
   the Dockerfiles.** `provides` versions the promise; `not_yet_declared` lists
   anything still owed, and is empty.
3. **[`docs/consuming.md`](docs/consuming.md)**: the same contract in prose, with
   the five rules a consumer inherits and the failure behind each.
4. **[`docs/compose.reference.yaml`](docs/compose.reference.yaml)**: a working
   compose file for the editor, generated from `consuming.json`.
5. **[`pins.json`](pins.json)** and **[`editor-pins.json`](editor-pins.json)**:
   every pinned version, digest and checksum, with where each came from.

What a build needs on the host: Docker with BuildKit, `python3` (standard
library only), and for an editor build a Chromium-family browser (see *The
editor image*). Nothing is pulled but the pinned bases and archives
`pins.json` and `editor-pins.json` name, each checked by digest or sha256.

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

## Profile images — adding a pinned input without moving a base tag

Every runtime set's tag ends in one shared suffix per image: the digest over `pins.json` and
`docker/minimal/` (the runner), and over those plus `docker/editor/`, `prime/` and `lockdown/` (the
editor). One byte changed in any of them moves **every** tag, including every published base's. So
an input that not every course needs does not enter them. It enters a **profile**: an image layered
on a shared base for a declared set, with its own pins and its own tag.

* **The pins** are `profiles/<name>.json`: `layers_on` (the runtimes the base set must contain),
  `images` (`runner`, `editor`) and `adds` (each entry: `kind`, `id`, `coordinates`, `sha256`).
  Nothing under `profiles/` or `docker/profile/` is an input of a base.
* **The recipe** is `docker/profile/Dockerfile`: `FROM ${BASE_IMAGE}`, with no ARG default. A build
  names the base by tag **and** image digest (`--base-digest sha256:<64 hex>`) and pulls nothing.
* **The tag** is `<repository>-<profile>:<set>-<arch>-<12 hex>`, for example
  `code-server-toolchain/runner-jvm-frameworks:gradle-java-kotlin-amd64-<12 hex>`. The 12 hex are a
  digest of the profile's name, **the base's own tag**, the profile's file and `docker/profile/`.
  So editing or adding a profile entry, or adding a whole new profile, moves no base tag and no
  other profile's tag; a change to the base moves the profile's tag, because the base's tag is in it.
* **Published names** are the base's published name plus the profile:
  `studyforge-code-toolchain-runner-jvm-frameworks` and `studyforge-code-toolchain-editor-jvm-frameworks`.

```sh
python3 docker/profile/profile_build.py --profile jvm-frameworks --image runner --print-tag
python3 docker/profile/profile_build.py --profile jvm-frameworks --image editor --print-plan   # JSON
python3 docker/profile/profile_build.py --profile jvm-frameworks --image runner --base-digest sha256:<base digest>
```

A consumer asks for a profile's tag with the command `consuming.json` names under `profile_tag` (one command for both
profile kinds; see `docs/consuming.md`, *Asking for a profile's tag*).

`--runtimes` is the base's declared set and defaults to what the profile layers on. A build is
refused while any entry still reads `TO-BE-PINNED`.

### Package entries: `python-wheels` and `npm-packages`

Two entry kinds a profile may carry beside `project` and `editor-extension`. They are built by a
second recipe, `docker/profile_packages/`, layered on the profile image; `docker/profile/` is not
edited for them, so the tag of a profile with neither kind is exactly what it was.

* `python-wheels`: `{kind, id, coordinates, requirements, sha256, platforms, imports?, remove_files?, allow_sdist?}`.
  `requirements` is a file under `profiles/<name>/` of `name==version --hash=sha256:...` lines (every
  dependency, no range) and `sha256` its digest. The fetch stage (the only one with a network) runs
  `pip download --require-hashes --only-binary=:all:`; the wheelhouse is kept read-only at
  `/opt/profile/wheelhouse` and installed with `pip install --no-index --find-links --require-hashes`.
  `remove_files` (paths under `site-packages`) are deleted after the hashed install and must exist;
  `allow_sdist` (a reason) lifts the wheels-only rule for the entry.
* `npm-packages`: `{kind, id, path, sha256, omit_optional?}`. `path` holds `package.json` and
  `package-lock.json` (every package with an `integrity`), `sha256` is the lockfile's digest. The fetch
  stage runs `npm ci` into a cache kept read-only at `/opt/profile/npm-cache` (named by
  `npm_config_cache`, with no `NODE_PATH`); `npm ci --offline` fills a course's `node_modules` from it.
  `omit_optional` (default false) skips optional dependencies, such as a platform binary. `imports`
  (optional) lists the specifiers the build proves import and type-check, for a package whose bare name
  cannot be imported; by default each dependency's name.
* `project`: a Gradle multi-project under `profiles/<name>/`, as above. In a profile that also holds a
  package entry it is warmed by this recipe into a read-only dependency cache (`GRADLE_RO_DEP_CACHE`) and
  proved by a build of a fresh copy in an empty Gradle user home with no network, so a profile of
  packages and projects never runs `docker/profile/`'s patch step. A profile with no `project` entry never
  runs the stage.

* `editor-extension` with `"install": "vsix"`: `{kind, id, install, url, sha256, provides, images: ["editor"], settings?}`.
  A `.vsix` the editor image installs into its extensions directory, offline: fetched in the fetch stage
  and refused by the entry's name unless its digest is `sha256`, installed with no network, and proved by
  `provides` (`publisher.name@version`) in `--list-extensions`. `settings` land in the editor's settings
  seed. An `editor-extension` with no `install` is the profile recipe's, as above, and unchanged. The
  runner image of the profile installs nothing for it.

A build refuses by entry and file name, before Docker starts, a missing file, a file that does not
match its pin, a requirement without a hash, a range, a lockfile package without an integrity, and a
platform the hashes do not cover. The build proves offline (`--network none`) that the imports work, that
`pip check` passes, that a wheel outside the wheelhouse is refused, that no index was consulted, and
that a fresh copy of the npm project installs, imports and type-checks.

```sh
python3 docker/profile_packages/package_build.py --profile fixture-packages --image runner --print-tag
python3 docker/profile_packages/package_build.py --profile fixture-packages --image runner --base-digest sha256:<base digest>
IMAGE=<tag> NPM_DIR=profiles/fixture-packages/npm sh docs/measurements/package-profile-offline-proof.sh
```

The `claude-sdks` profile holds the Claude SDKs a course's practices use: the Python wheels (amd64) and
npm packages above, and a Gradle project of three subprojects (the Java SDK jars with JUnit 5.10.2, the
Kotlin SDK jars with the Java SDK and JUnit, and `kotlin.test`). Its offline proof runs a course practice
in each of Python, TypeScript, Java and Kotlin, and an MCP server and client over stdio, with nothing
mounted but the practice:

```sh
IMAGE=<tag> PRACTICE=/path/to/practice-folder sh docs/measurements/claude-sdks-offline-proof.sh
```

The editor image of `claude-sdks` shows diagnostics in a `.ts` file with the shared editor's own TypeScript
support and, for a `.py` file, through the pinned `basedpyright` extension (MIT, its language server inside the
archive); the shared editor carries a Python extension with no language server, so without it a Python file
shows none. `docs/measurements/editor-diagnostics-offline.py <editor image>` proves both with the network cut
off (an internal Docker network) in a headless browser, and fails if a planted error shows none or a clean
file shows one.

⛔ A profile with a package entry is planned and built through `package_build.py`; the profile
planner's own tag does not name the packages. `fixture-packages` is the fixture that proves both kinds.

**The `jvm-frameworks` profile** carries a JVM course's framework modules' libraries (Spring Boot,
Spring Data with an embedded H2 database, Spring Security and Ktor), so no shared base carries them.
It layers on `gradle,java,kotlin`. Its entries are placeholders until their coordinates and
checksums are pinned; its tag is computed today, and its dependencies are not yet fetched or warmed.
A new runtime that needs its own image is added the same way, as its own profile file.

**The `project` entry kind.** An entry `{"kind": "project", "id", "path", "sha256"}` names a Gradle
multi-project directory `profiles/<name>/<path>/` (one subproject per distinct dependency set) and
the sha256 of its `gradle/verification-metadata.xml`. The directory's bytes, and the warmers in
`prime/` that warm it, are folded into that profile's tag (and into no other profile's or base's);
`dependency` entries and the `TO-BE-PINNED` rule are unchanged. Before Docker starts, a build
refuses by entry and file name a directory or checksum file that is missing or does not match the
pin. The recipe then warms each project with `prime/warm-gradle.sh warm` (the course layer's own
warm step, network on, every file checked against the project's metadata), keeps the warmed
`modules-2` as a read-only cache at `/opt/profile/gradle-ro-cache` named by `GRADLE_RO_DEP_CACHE`
(the image sets no `GRADLE_USER_HOME`, so a course prime layered on it keeps its own), and proves
with `--network=none` that a fresh copy of each project builds in an EMPTY Gradle user home that
has only that cache. The named contexts `profile-projects` and `warmers` carry the project and the
warmers. `profiles/fixture-libs.json` is a small fixture (a Kotlin module, JUnit, Gson,
commons-lang3 and kotlinx-coroutines, no framework) that exercises the kind end to end; it is not a
course's profile.

**The `editor-extension` entry kind.** An entry `{"kind": "editor-extension", "id", "url", "sha256",
"images", "settings"}` names a `.zip` or `.tar.gz` archive that an editor extension needs and would
otherwise download from the network at first use, pinned by an exact address and a sha256, and the
images it belongs to. The recipe's fetch stage (`docker/profile/fetch_extension.py`) downloads it,
refuses by entry name an archive whose bytes are not the pinned ones, and unpacks it (without its
first `strip` path components) to `/opt/profile/editor-extensions/<id>/` in the images the entry
names and in no other. `platform` (for an archive of machine code) refuses a build for another
platform by name. `settings` are written as one `// @runtime kotlin` block into the editor's
settings seed, so an editor of a set without the profile has neither the archive nor the setting.
`patches` are exact-string edits of a file the base installed, each checked against the file's
sha256 before and after (`apply_patches.pl`). The editor's own recipe, `editor-pins.json` and every
base tag are untouched, because a profile's inputs are in no base's tag.
`profiles/kotlin-editor.json` is the first use: the Kotlin language server `1.3.13`, a Temurin JDK
`21.0.9+10` to run it on (its embedded compiler cannot read the runner's JDK 25 version string), and
two patches that let the pinned `fwcd.kotlin` `0.2.36` activate on this code-server (it reads the
`navigator` global, which the extension host rejects, and it waits on a first-run question).
Measured on that profile's editor image, network cut off: a planted type error shows a diagnostic
about 3.5 s after the page opens, a member completion on a `String` lists its members, the
language server holds about 1 GiB with one `.kt` file open, and the image grows by 0.45 GB.

## Publishing an image

`docker/publish.py` names an image `<namespace>/<published name>:<tag>`, where the published name is
`studyforge-code-toolchain-runner` or `studyforge-code-toolchain-editor` (the local build names stay
`code-server-toolchain/runner` and `code-server-toolchain/editor`) and the tag is
the one the build computes for this checkout, never a hand-written one. ⛔ **The
namespace is read from the `TOOLCHAIN_NAMESPACE` environment variable and from
nowhere else**: the script refuses to run when it is unset, and no namespace is
written in this repository. Log in to your registry yourself first; the script
never logs in.

```sh
export TOOLCHAIN_NAMESPACE=<your registry namespace>
python3 docker/publish.py runner --runtimes java,maven --dry-run   # prints the commands, runs none
python3 docker/publish.py runner --runtimes java,maven             # builds and tags locally
python3 docker/publish.py runner --runtimes java,maven --push      # and pushes
```

`editor` takes the same flags. ⭐ Pin a pulled image by the digest `docker push`
prints (`<namespace>/studyforge-code-toolchain-runner@sha256:<digest>`), not by its tag: a digest names
one image for good. `tests/test_publish.py` holds all of this.

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
so a report can name the toolchain that produced a measurement. ⭐ **What that
tag promises, and what forces a new one, are `runner.image.tag` in
[`consuming.json`](consuming.json)** and
[`docs/consuming.md`](docs/consuming.md)'s *What the runner's tag promises*.
⛔ **An editor-only change moves no runner tag:** the editor's inputs are not
the runner's, and a test measures it both ways.

`python3 docker/minimal/build.py --record-maven` re-derives the Maven warm list
into `.work/record/` for a person to review and copy into `pins.json`.

`--pull never` builds from what this host already holds: every image the build
starts FROM must be present, and one that is not is refused by name before
Docker builds anything. `--pull missing`, the default, fetches an absent base by
its pinned digest. ⚠️ `--pull` is about images: an archive the Dockerfile names
is still fetched by `ADD --checksum` when BuildKit has not cached it.

### A corpus's practice dependencies — `--prime DIR`

⛔ **A reader's graded run happens in this image, under `--network none`**, so
whatever a corpus's practices depend on must already be inside it: a download
would not be slow, it would simply fail. `--prime DIR` warms them from that
corpus's own build files, exactly as the editor image warms a consumer's
 — the contract, the version guards and the two warmers are
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

In PowerShell on Windows, which has no `id` and whose users have no uid, the
same line takes `runner.runs_as.powershell_run_value` and continues with a
backtick (`python3 consuming/consuming.py --run-line --powershell`):

```powershell
docker run -d --name studyforge-runner-<source> --init --network none `
  --user "1000:1000" -v "<source root>:/work" <tag>
```

⭐ Every command in this README runs on Windows as on Linux and macOS (a course publishes and runs from Windows, on Docker Desktop). Where a
POSIX shell and PowerShell spell one differently, both are shown; elsewhere,
`python3` is `python` or `py -3` on Windows.

- `--network none`: nothing a build does inside it reaches off the machine.
- `--user`: files the build writes are owned by the reader, not by root. On
  Docker Desktop for Windows they belong to the Windows user whatever the uid,
  so any ordinary user serves.
- `--init`: the idle process is reaped, so a stop is prompt.
- No `-p`: nothing listens.

⛔ **That line is not the authority; it is a rendering of one.** The runner's
run shape is declared as data in [`consuming.json`](consuming.json) under
`runner`, beside the editor's block, and the line above is what
`python3 consuming/consuming.py --run-line` prints from it. A test asserts the
two are the same, so a consumer copying this prose and a generator reading that
block get the same container. [`docs/consuming.md`](docs/consuming.md) is the
prose half of both blocks.

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
python3 docker/editor/build.py --runtimes java,maven --pull never
python3 docker/editor/build.py            # gradle,java,kotlin,node,python
```

`--pull never` holds for the runner's build too, when the editor's build has to
make it first: the bases of both are checked before either starts.

⛔ **An editor build needs a Chromium-family browser on the host as well as
Docker**, because the image is tagged only after its lockdown has been seen to
RUN in a real workbench session (the lockdown section, below). `--print-tag`
computes and needs neither.

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
  the one Debian package the runner's Python needs on this base, and the code
  face's release archive and files (by sha256). Keeping them
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
- ⭐ **The editor draws code in the study page's face.** The page sets code
  in JetBrains Mono (SIL Open Font License 1.1), regular with bold keywords.
  The image takes the same two files out of the same release archive, each by
  the sha256 `editor-pins.json` records under `face`, serves them beside the
  workbench's stylesheet and declares them there, and the lockdown's manifest
  makes the family the editor's default (`configurationDefaults`), so a
  reader's own `editor.fontFamily` still wins. ⛔ Ligatures are off by default
  (`editor.fontLigatures`), as on the page: `!=` drawn as one not-equal sign
  reads as a different operator in code the reader must type, so the page sets
  `font-variant-ligatures: none` on code and the editor draws `!=` and `->` as
  the characters they are, measured in a browser. The licence ships beside them.
  ⚠️ The workbench draws in the reader's browser, so a face held on disk would
  never reach it, and its content policy allows fonts from its own origin
  only.
- ⛔ **The editor makes no outbound connection of its own.** Measured on an
  idle practice session before this: the server called code-server's update
  check (api.github.com) and its telemetry (v1.telemetry.coder.com), the Java
  language server fetched Gradle's version list (services.gradle.org), and the
  reader's browser queried the open-vsx.org gallery from inside the frame. Each
  is off where a compose `command:` cannot drop it: the entrypoint appends
  `--disable-update-check --disable-telemetry` to whatever command arrives,
  `EXTENSIONS_GALLERY={}` empties the gallery (every extension here is
  installed from a pinned file at build time), and the lockdown manifest's
  defaults turn the extensions' own off -- Red Hat telemetry, JSON schema
  downloads, npm package lookups and type acquisition, and Maven and Gradle
  imports offline. ⚠️ Buildship, inside the Java language server, fetches the
  published Gradle version list whenever its cache is missing or a day old,
  whatever the Gradle or proxy settings say; the image sets `XDG_CACHE_HOME`
  to its XDG default (`~/.cache`) so that cache has one place, and the
  entrypoint writes an empty list there on every start with a modification
  time that never ages. The list feeds version pickers this editor does not
  show.
  `tests/test_editor_egress.py` samples the container's socket table and the
  page's requests over a session and fails on any that leave the host.
- ⭐ **A closed practice session is released in minutes, not hours.** The image
  sets `CODE_SERVER_RECONNECTION_GRACE_TIME` to 180 seconds (upstream's is
  three hours). A window that closes cleanly is disposed at once; one that
  ends without saying so (a crash, a killed browser, a machine that sleeps)
  keeps its extension host and language server until the grace ends, and a
  connection that comes back inside it reconnects to the same session. It is
  an `ENV` because a compose `command:` replaces `CMD`; ⚠️ it also overrides a
  `--reconnection-grace-time` flag, so a consumer who wants another value
  sets the variable.

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
  marketplace tool) and installs it with the pinned extensions.
- ⛔ **INSTALLED IS NOT RUNNING, and the image is tagged on the RUNNING fact**
  ([`docker/editor/activation.py`](docker/editor/activation.py)). ⚠️ **Once,
  the extension was installed, listed by `code-server --list-extensions`,
  present in `extensions.json`, parsed under the image's own node and inside
  its engine range — and the extension host activated it in NO session, with
  no error**, because the workbench's Restricted Mode had disabled it. ⛔ **A
  check that reads INSTALLATION cannot see ACTIVATION**, and the installed-list
  check that used to carry this guarantee passed in every one of those rounds.
  ⭐ **So the build now writes an image ID rather than a tag, opens a REAL
  workbench session in that image with a headless browser against an
  UNTRUSTED mounted folder — the shape every consumer serves — and applies
  the tag only once the extension host's log shows the extension activating
  AND the extension's own banner shows it ran.** ⛔ **A host with no browser
  refuses the build; it does not skip the proof.** The browsers it looks for,
  and the `STUDYFORGE_BROWSER` override, are that module's.
- ⭐ **The proof runs on any engine, Docker Desktop and Windows included.** Its folder is a named volume seeded through the Docker
  CLI's stdin (`docker/editor/engine.py`), never a bind of a host temporary
  directory: Docker Desktop shares no host `/tmp` and refuses one, and Windows
  has none. The browser's profile and `TMPDIR` are one short host directory,
  and a failed proof quotes the browser's own last lines. ⭐ Every script runs
  the plain `docker` CLI, so `DOCKER_CONTEXT` (or the current context) picks
  the engine, and nothing here switches a context.
- ⛔ **`--disable-workspace-trust` is part of the image's own `CMD`, and it is
  load-bearing.** ⚠️ The contract carried it in `consuming.json`'s
  `editor.command` while the image's `CMD` did not, so every consumer that
  started the image on its own command line rather than through the compose
  template got a workbench in Restricted Mode with no lockdown at all — which
  is exactly how that defect reached a reader, twice. ⭐ The manifest's
  `capabilities.untrustedWorkspaces` is the other half: the flag covers a
  consumer who keeps the image's command, the declaration covers one who
  replaces it.
- ⛔ **The COMMAND SURFACE is confined, and hiding a surface is not the same
  thing** ([`lockdown/allowed.js`](lockdown/allowed.js)). ⚠️ Closing
  the Explorer leaves the reader one `Ctrl+P` from being somewhere else, and a
  reader's own screenshot showed the palette open inside a practice frame
  offering Go to File, Show and Run Commands, Search for Text, Open Quick
  Chat, Go to Symbol, Start Debugging and Run Task. ⭐ **What is written down
  is an ALLOW-LIST of what a practice NEEDS** — the caret, the editor's own
  actions, completion, find, and `Ctrl+S` — **and every other default
  keybinding's removal is DERIVED from it against the workbench's own default
  keybinding document.** ⛔ **A deny-list is the wrong shape**: it is wrong the
  next time the workbench gains a command, and nothing would say so. ⭐ The
  tab guard is the other half, because removing a keybinding does not
  unregister a command: any editor tab that is not the file that window's URL
  opened is closed, whatever opened it, and no surface is named in the source.
- ⛔ **The editor has no chat, agent or AI surface, and that is the PRODUCT,
  not a setting** ([`docker/editor/no_ai.js`](docker/editor/no_ai.js)). ⚠️
  Deleting the bundled chat extension and the Copilot modules left the
  workbench's own chat: a reader saw a "Build with Agent" side bar with a chat
  input in a practice frame. ⭐ The build edits both workbench bundles: the AI
  switch (`chat.disableAIFeatures`) defaults on, the chat entitlement is always
  hidden, and the command registry and the palette refuse every AI command id,
  so asking for the chat answers "command not found". ⛔ A seeded setting would
  miss every existing volume, whose `settings.json` the entrypoint never
  touches; these edits hold on a fresh volume and on an existing one, even one
  whose settings turn the switch back off. Each edit must find exactly one
  anchor, or the build fails naming it. ⭐ The secondary side bar, where the
  chat's hidden container still lives, is hidden at EVERY start by the
  layout's own override, before the first layout: it never paints, not even
  for the second or so a Java frame spends opening its projects, on a first
  start or a reload (`tests/test_editor_layout.py` and
  `tests/test_editor_no_ai.py` read every frame).
- ⛔ **A changed editor is never run from a browser's cache.** ⚠️ The
  workbench is served under `/stable-<commit>/static/` for a year, and that
  commit was code-server's own, the same for every image on one release: a
  reader's browser kept running an older image's `workbench.js` against a newer
  image. ⭐ The build rewrites the commit to a digest of every file under the
  product, in `product.json` and in every bundle that bakes it in, as the last
  step that writes the product. Any edit gives a new path; identical product
  files keep the same one, so an unchanged rebuild downloads nothing.
- ⛔ **This is an INTEGRITY clause, not a tidiness one.** ⚠️ `files.readonlyExclude`
  is what makes a Submit mean anything — the test that judges the reader is not
  theirs to edit — and it is an **object setting, which VS Code MERGES across
  scopes**. Measured in a real session: a workspace value of
  `{"Main.java": true}` became `{"MainTest.java": true, "Main.java": true}`
  after one `ConfigurationTarget.Global` write, and the user settings file on
  disk carried it. ⛔ **So a reader who reaches the settings editor can make
  their own test writable**, and both ways in — the editor and the JSON — are
  confined.
- ⛔ **The removals are SEEDED by the entrypoint, before any session exists.**
  ⚠️ Measured: the workbench reads `<user data dir>/User/keybindings.json` when
  a **session starts** and ignores a write made while one is open — the file
  sits on disk, correct, and every key still fires. ⭐ So
  [`docker/editor/seed/keybindings.json`](docker/editor/seed/keybindings.json)
  is generated, baked into the image and written on **every** start, unlike
  `settings.json`, which is the reader's and is written only when absent.
  Regenerate it with
  `python3 docker/editor/confinement.py --write <image>...`, naming one editor
  image per runtime set in `confinement.SEED_SETS` — ⛔ never by hand, and
  never from one set alone: one seed serves every set, and each set's
  extensions bind keys of their own.
- ⛔ **And the image is tagged on what the workbench ALLOWS, not on what the
  file says** ([`docker/editor/confinement.py`](docker/editor/confinement.py)).
  ⭐ The same session `activation.py` opens is driven by a headless browser
  that **presses** `Ctrl+Shift+P`, `Ctrl+P`, `Ctrl+,`, `F5` and the rest and
  looks at the page for what appeared — and then presses the keys a practice
  needs, types into the one file and saves it, because ⚠️ **a confinement that
  broke the practice would pass every negative clause.** The extension's own
  report is the exhaustive half beside it: it derives the removals the
  allow-list implies from **this** workbench's keybindings and says how many
  the session did not load, so a code-server bump that adds a command refuses
  the build instead of shipping quietly.
- ⭐ **It reads no setting and knows no corpus.** Which file a window shows is
  decided by that window's own URL. It contributes
  `studyforge.practice.main` and `studyforge.practice.test` only so the
  workbench accepts the keys a study server writes, and treats a change to that
  section as the one signal that the practice moved. ⭐ Its manifest also
  carries the editor's defaults (`configurationDefaults`): the page's code
  face with its ligatures off, and the extensions' call-homes switched off (both
  above). They are defaults, so a setting of the reader's wins.
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
  compile, a test compile and `test`; a Maven build must compile a source,
  compile a test and run it. Otherwise the build fails, naming the project.
  ⭐ A Maven module with no sources is primed through its POM, and named:
  Maven resolves what a POM declares before a step runs, whether or not the
  step then finds a source. ⭐ A test that fails in the consumer's own build
  is named as the consumer's finding and does not fail the prime: the run it
  failed in resolved what it needed.
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
project must provide, and the rules it must not break, are in
[`docs/consuming.md`](docs/consuming.md) for a person and in
[`consuming.json`](consuming.json) for a generator — ⛔ **a consumer reads those
and never this repository's `Dockerfile`.**

[`docs/compose.reference.yaml`](docs/compose.reference.yaml) is a complete,
working compose file, ⛔ **a template to copy and adapt, never an `include:`**:
the mount list is exactly the part that must differ per project. It is
**generated** from `consuming.json` and nothing else, so the contract and the
template cannot drift.

```sh
python3 consuming/consuming.py --check    # the rules, on the real contract
python3 consuming/consuming.py --write docs/compose.reference.yaml
```

[`consuming.json`](consuming.json) carries one block per image this component
builds — `editor` and `runner` — and `not_yet_declared` is now empty: both run
shapes and both tag promises are stated. The five rules a consumer inherits,
each with the failure that bought it, are
loopback-only publishing, the sources and nothing else, the repository owner's
uid:gid, a bind source that exists on the host before the container starts, and
a writable root filesystem — the entrypoint repairs the passwd record at every
start and the primed caches are written under `/opt`, so a read-only root breaks
the editor at start and every graded run in it.
⛔ **No Docker socket is mounted into the editor, or anywhere else**: it is an
IDE with a shell on a port, and a socket there is root on the host.

## Tests

```sh
python3 -m unittest discover -s tests -v                   # the plans, pins and static checks
TC_DOCKER=1 python3 -m unittest tests.test_image -v        # builds and runs the runner
TC_DOCKER=1 python3 -m unittest tests.test_editor_image -v # builds and runs the editor
TC_DOCKER=1 python3 -m unittest tests.test_editor_layout -v # neither side bar is ever painted
TC_DOCKER=1 python3 -m unittest tests.test_editor_agent_host -v # no agent host, no Copilot CLI
TC_DOCKER=1 python3 -m unittest tests.test_editor_no_ai -v # no chat, agent or AI surface
TC_DOCKER=1 python3 -m unittest tests.test_editor_static_path -v # a changed editor is fetched, an unchanged one is not
TC_DOCKER=1 python3 -m unittest tests.test_editor_face -v # the page's face, as drawn
TC_DOCKER=1 python3 -m unittest tests.test_editor_idle -v # a closed session is released
TC_DOCKER=1 python3 -m unittest tests.test_editor_egress -v # no outbound connection
TC_DOCKER=1 python3 -m unittest tests.test_editor_selection_image -v # the selected sets
TC_DOCKER=1 python3 -m unittest tests.test_prime_image -v   # the prime, warm and offline
TC_DOCKER=1 python3 -m unittest tests.test_runner_prime_image -v # a graded run, offline
TC_DOCKER=1 python3 -m unittest tests.test_consuming_image -v # the compose contract, brought up
```

`tests/test_lockdown.py` needs no Docker: it packs the extension with the
standard library, runs it against a stub `vscode` module with `node`, and
reads the packed identity against this README and the build's expected list.
⭐ `TC_DOCKER=1 python3 -m unittest tests.test_lockdown_activation -v` is the
RUNNING half: it opens a real workbench session in the image with a headless
browser and requires both log lines, and it plants against itself — the same
image with `--disable-workspace-trust` taken out of its command is refused,
naming what was missing. ⛔ It needs Docker and a browser, and it skips only
when `TC_DOCKER` is unset, never because a browser is absent.
`tests/test_consuming.py` needs none either: it reads every value
`consuming.json` states about the image back out of the build's own plan, the
Dockerfile and the lockdown manifest, resolves every key `docs/consuming.md`
names, and plants a violation of each rule to see it refused. It also plants a
version bump in a temporary copy of the build inputs and measures that the tag
moves, and that an EDITOR-only bump moves the editor's tag and not the runner's.
`tests/test_consuming_runner.py` is the runner block's own: the rules it
carries, and the documented `docker run` and `docker exec` lines read back out
of the block that renders them.
`tests/test_publish.py` holds the publish step to its namespace variable, its dry run and its
explicit push. `tests/test_pull.py` holds `--pull never` to every image both Dockerfiles start
FROM, with Docker stood in for. `tests/test_no_citations.py` reads every
tracked file, and a test module's docstrings and comments, and refuses a rule
id, a spec section or a work item's id: this repository is read on its own, so
each file states its reason instead, the rendered compose reference included.

`tests/test_consuming_image.py` copies `docs/compose.reference.yaml` VERBATIM
into an empty directory, supplies only what that file asks for by name, and
brings it up: the editor answers its health path on loopback and nowhere else,
a file it writes into the mounted sources belongs to the host user, a uid that
is not the image's own starts (and the same image without its entrypoint's
`fixuid` does not), a missing bind source is created root-owned and cannot be
written, a read-only root filesystem never starts at all, and no Docker socket
is anywhere near it. It also builds a SECOND image from a second declared set
and brings it up beside the first, on its own port: two consumers holding two
tags, both healthy at once. It runs on a host whose reader's editor already holds
the declared port: the first consumer then takes a free port, and its file is
asserted to be the reference with that port alone replaced.

The image tests build a full image and a `shell`-only image, run every smoke
project under `docker/minimal/smoke/` with `--network none` (each passes, and a
planted failure fails), plant a wrong checksum, a wrong version and a changed
warm file in temporary copies (each stops the build), and exec into a container
started by the documented run line. They remove the images they build unless
`TC_KEEP_IMAGES=1`.
