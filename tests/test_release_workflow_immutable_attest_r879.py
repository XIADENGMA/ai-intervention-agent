"""R879: the GitHub Release job survives release immutability, and signs what it ships.

Release immutability is a repository setting (generally available since October 2025).  Once a
Release is published, its tag and its assets are locked: nothing can be added, replaced or
deleted, and GitHub adds a signed *release attestation* for the files.  ``release.yml`` was written
before that, and its last job, ``github-release``, had two problems that the setting turns from
"harmless" into "breaks the release":

* **A re-run replaced files.**  When a Release for the tag existed, the step ran
  ``gh release upload --clobber``, which deletes the same-named assets first.  The step is the one
  that is re-run when a *later* step of the job fails (the clean-up of old Releases), so the
  re-run reached an already published Release.  On an immutable one that upload is refused and the
  job turned red; on a mutable one it silently swapped the files under a Release that had been
  public for minutes.
* **A leftover draft made the job green with nothing published.**  ``gh release view`` finds a
  draft by its tag, so a draft left behind by a killed runner sent the step down the "upload
  again" branch, which ends green and leaves the draft a draft.  (From the source of ``gh``; it
  was not tried on GitHub.)

The job now does this, in this order, and every part of it is pinned below:

1. **Look at the tag's Release first.**  A leftover draft stops the job with an error that says
   what to delete; an already published Release skips everything up to the clean-up, so a re-run is
   safe and the clean-up still runs.
2. **Attest the build** with ``actions/attest`` (SLSA build provenance for the sdist, the wheel and
   the VSIX), keep the bundle as ``ai-intervention-agent-<version>.sigstore.json`` next to them
   (OpenSSF Scorecard's *Signed-Releases* looks for that suffix) and verify the files against it
   with ``gh attestation verify --bundle ... --repo ... --signer-workflow ...`` before anything
   is published.
3. **Create the Release as a draft, upload every file, check them, publish last** (the order
   GitHub documents for immutable releases): the names and the sha256 digests that GitHub reports
   must equal the local files, or the job fails while everything can still be thrown away.
4. **Say what happened** (``isImmutable``, the release attestation) in notices only: the Release
   is out by then, and a repository that has not switched immutability on is a legal state.

``id-token: write`` and ``attestations: write`` go to this job only.  The ``build`` job runs
``npm ci`` and the whole CI gate and must not be able to ask Sigstore for a certificate.

What this file can and cannot show.  The job's shell scripts are run, the way ``bash -e`` runs them
in Actions, against a fake ``gh`` that keeps one Release in a JSON file, logs every call and
refuses what GitHub refuses (an upload to a published immutable Release, a second Release for a
tag, a ``gh attestation verify`` with other flags or another bundle), so each scenario asserts what
was done to the Release and in which order, not only the exit code.  ``actions/attest`` and the
real GitHub API are not run here.  The flags of ``gh attestation verify`` and ``gh release verify``
were tried once by hand on a real SLSA bundle and a real immutable Release (the ones of
``cli/cli`` v2.103.2), and the first real run of the job is the rest of the proof.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "release.yml"

REPOSITORY = "XIADENGMA/ai-intervention-agent"
TAG = "v1.9.0"
#: The condition the three scripted steps carry; the simulation refuses any other one.
GATE = "steps.state.outputs.state == 'none'"

#: The step this job had before R879, verbatim, to show what the change fixes.
OLD_RELEASE_STEP = """\
set -euo pipefail
tag="${GITHUB_REF_NAME}"

prerelease_flag=""
if [[ "$tag" == *-* ]]; then
  prerelease_flag="--prerelease"
fi

# 如果 Release 不存在则创建；存在则仅上传/覆盖产物（避免 tag 重跑导致失败）
if gh release view "$tag" >/dev/null 2>&1; then
  gh release upload "$tag" dist/* vsix/*.vsix --clobber
else
  gh release create "$tag" dist/* vsix/*.vsix --title "$tag" --generate-notes $prerelease_flag
fi
"""


# ---------------------------------------------------------------------------------------------
# The workflow, read as data
# ---------------------------------------------------------------------------------------------


@cache
def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


@cache
def _workflow() -> dict[str, Any]:
    return yaml.safe_load(_text())


def _jobs() -> dict[str, dict[str, Any]]:
    return _workflow()["jobs"]


def _steps() -> list[dict[str, Any]]:
    return _jobs()["github-release"]["steps"]


def _step(marker: str) -> dict[str, Any]:
    """The one step of the job whose script (or ``uses``) contains *marker*."""
    found = [
        s for s in _steps() if marker in (s.get("run") or "") + (s.get("uses") or "")
    ]
    assert len(found) == 1, (
        f"expected exactly one step with {marker!r}, found {len(found)}"
    )
    return found[0]


def _index(step: dict[str, Any]) -> int:
    return next(i for i, s in enumerate(_steps()) if s is step)


def _state_step() -> dict[str, Any]:
    found = [s for s in _steps() if s.get("id") == "state"]
    assert len(found) == 1, "the job needs exactly one step with `id: state`"
    return found[0]


def _attest_step() -> dict[str, Any]:
    return _step("actions/attest@")


def _bundle_step() -> dict[str, Any]:
    return _step("gh attestation verify")


def _release_step() -> dict[str, Any]:
    return _step("gh release create")


def _cleanup_step() -> dict[str, Any]:
    return _step("gh release delete")


def _files_array(script: str) -> list[str]:
    """The words of ``files=( ... )`` in the release script."""
    match = re.search(r"^files=\((?P<body>[^)]*)\)\s*$", script, re.MULTILINE)
    assert match, (
        "the release script must name what it ships in one `files=(...)` array"
    )
    return re.findall(r'"[^"]*"|\S+', match.group("body"))


# ---------------------------------------------------------------------------------------------
# What the file says (static)
# ---------------------------------------------------------------------------------------------


def test_the_release_job_may_ask_for_attestations_and_nothing_else_new() -> None:
    assert _jobs()["github-release"]["permissions"] == {
        "actions": "read",
        "contents": "write",
        "id-token": "write",
        "attestations": "write",
    }


def test_only_publish_and_github_release_can_get_an_oidc_token() -> None:
    """``build`` runs ``npm ci`` and the CI gate; ``open-vsx`` runs a pinned ``ovsx``."""
    assert _workflow()["permissions"] == {"actions": "read", "contents": "read"}
    holders = {
        name: job["permissions"]
        for name, job in _jobs().items()
        if {"id-token", "attestations"} & set(job.get("permissions", {}))
    }
    assert set(holders) == {"publish", "github-release"}, holders
    assert holders["publish"] == {"actions": "read", "id-token": "write"}
    for name in ("build", "open-vsx"):
        assert "permissions" not in _jobs()[name], (
            f"{name} must keep the read-only default"
        )


def test_the_attest_action_is_pinned_to_a_commit() -> None:
    uses = _attest_step()["uses"]
    assert re.fullmatch(r"actions/attest@[0-9a-f]{40}", uses), uses
    assert re.search(
        rf"^\s+uses: {re.escape(uses)} # v\d+\.\d+\.\d+$", _text(), re.MULTILINE
    ), "keep the `# vX.Y.Z` comment: Dependabot reads it to propose the next version"


def test_the_attestation_covers_every_file_the_release_ships() -> None:
    subjects = _attest_step()["with"]["subject-path"].split()
    assert subjects == ["dist/*", "vsix/*.vsix"]
    shipped = _files_array(_release_step()["run"])
    assert len(shipped) == 3
    assert shipped[:2] == subjects
    assert re.fullmatch(
        r'"attestation/ai-intervention-agent-\$\{tag#v\}\.sigstore\.json"', shipped[2]
    ), (
        "the bundle ships as <name>-<version>.sigstore.json (Scorecard's Signed-Releases suffix)"
    )


def test_every_file_is_checked_against_the_bundle_with_repo_and_signer_pinned() -> None:
    step = _bundle_step()
    script = step["run"]
    assert re.search(r"for f in dist/\* vsix/\*\.vsix; do", script)
    verify = re.search(
        r"gh attestation verify \"\$f\" \\\n(?P<flags>(?:\s+--.*\n?)+)", script
    )
    assert verify, "gh attestation verify must run once per file"
    flags = verify.group("flags")
    assert '--bundle "$bundle"' in flags
    assert '--repo "$GITHUB_REPOSITORY"' in flags
    assert (
        '--signer-workflow "$GITHUB_REPOSITORY/.github/workflows/release.yml"' in flags
    )
    assert step["env"]["BUNDLE_PATH"] == "${{ steps.attest.outputs.bundle-path }}"
    assert _attest_step()["id"] == "attest"


def test_the_steps_run_in_the_order_look_attest_check_publish_clean_up() -> None:
    order = [
        _index(step)
        for step in (
            _state_step(),
            _attest_step(),
            _bundle_step(),
            _release_step(),
            _cleanup_step(),
        )
    ]
    assert order == sorted(set(order)), order


def test_all_but_the_look_and_the_clean_up_wait_for_a_tag_without_release() -> None:
    assert "if" not in _state_step()
    assert "if" not in _cleanup_step(), (
        "the clean-up must also run when the Release exists"
    )
    for step in (_attest_step(), _bundle_step(), _release_step()):
        assert step["if"] == GATE


def test_the_release_is_a_draft_without_files_and_published_after_the_check() -> None:
    script = _release_step()["run"]
    create = re.search(
        r'^gh release create "\$tag" "\$\{create_args\[@\]\}"$', script, re.M
    )
    assert create, "gh release create must be given the tag and the flags, and no files"
    args = re.search(r"^create_args=\((?P<body>[^)]*)\)$", script, re.MULTILINE)
    assert args, (
        "the flags of gh release create must be in one `create_args=(...)` array"
    )
    assert {"--draft", "--verify-tag"} <= set(args.group("body").split())
    assert "create_args+=(--prerelease)" in script
    upload = script.index('gh release upload "$tag" "${files[@]}"')
    check = script.index('if [[ "$want" != "$have" ]]')
    publish = script.index('gh release edit "$tag" --draft=false')
    assert create.start() < upload < check < publish
    assert script.count("gh release edit") == 1
    failures = [m.start() for m in re.finditer(r"exit 1", script)]
    assert failures and all(at < publish for at in failures), (
        "give up before the publish"
    )


def test_nothing_overwrites_a_release_and_the_clean_up_keeps_the_tags() -> None:
    for name, job in _jobs().items():
        for step in job["steps"]:
            assert "--clobber" not in (step.get("run") or ""), (
                f"{name}: {step.get('name')}"
            )
    cleanup = _cleanup_step()["run"]
    assert "--cleanup-tag" not in cleanup, (
        "an immutable Release's tag cannot be deleted anyway"
    )
    assert 'gh release delete "$old_tag" --yes' in cleanup


def test_the_workflow_has_no_warning_annotations() -> None:
    """The project keeps release logs free of warnings (see the OPEN_VSX_TOKEN notice test)."""
    assert "::warning::" not in _text()


# ---------------------------------------------------------------------------------------------
# What the scripts do (run against a fake gh)
# ---------------------------------------------------------------------------------------------

#: The fake ``gh``.  It models one tag's Release (draft or published, immutable or not, with
#: assets and their digests), logs every call as a JSON line and answers like the parts of GitHub
#: this job touches.  Anything it does not know exits 2 so that a new call cannot go unnoticed.
FAKE_GH = r"""
import hashlib
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
state_path = Path(os.environ["FAKE_GH_STATE"])
state = json.loads(state_path.read_text())
with open(os.environ["FAKE_GH_LOG"], "a") as log:
    log.write(json.dumps(args) + "\n")


def save():
    state_path.write_text(json.dumps(state))


def fail(message, code=1):
    print(message, file=sys.stderr)
    sys.exit(code)


def digest(path):
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def publish(release):
    release["draft"] = False
    release["immutable"] = bool(state["immutable_setting"])


def add_assets(release, files):
    if release["draft"] is False and release["immutable"]:
        fail("HTTP 422: Cannot upload assets to an immutable release", 1)
    for i, name in enumerate(files):
        if not Path(name).is_file():
            fail("no such file: " + name)
        base = Path(name).name
        if base in release["assets"] and "--clobber" not in args:
            fail("HTTP 422: asset under the same name already exists: " + base)
        value = digest(name)
        if state["corrupt_upload"] and i == 0:
            value = "sha256:" + "0" * 64
        release["assets"][base] = {"digest": value, "size": Path(name).stat().st_size}


if not (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")):
    fail("gh: To use GitHub CLI in a GitHub Actions workflow, set the GH_TOKEN variable", 4)

tag = state["tag"]
release = state["release"]
words = args[:2]

if args[:1] == ["api"]:
    if args[1:2] != ["repos/" + state["repository"] + "/releases"] or "--paginate" not in args:
        fail("fake gh: unsupported api call: " + " ".join(args), 2)
    pages = [[{"id": 7, "draft": True, "tag_name": "v0.0.1-other"}]]
    pages.append([{"id": 8, "draft": release["draft"], "tag_name": tag}] if release else [])
    print("\n".join(json.dumps(page) for page in pages))
elif words == ["release", "view"]:
    if args[2] != tag or release is None:
        fail("release not found")
    if state["view_fails_after_publish"] and release["draft"] is False:
        fail("HTTP 502: Bad Gateway")
    if "--json" not in args:
        print("title:\t" + tag)
    else:
        every = {
            "isDraft": release["draft"],
            "isImmutable": release["immutable"],
            "assets": [{"name": n, **a} for n, a in release["assets"].items()],
        }
        print(json.dumps({k: every[k] for k in args[args.index("--json") + 1].split(",")}))
elif words == ["release", "create"]:
    if args[2] != tag:
        fail("fake gh: wrong tag " + args[2], 2)
    if release is not None:
        fail("HTTP 422: a release with the same tag name already exists: " + tag)
    value_flags = {"--title", "-t", "--notes", "-n", "--target"}
    files, skip = [], False
    for word in args[3:]:
        if skip:
            skip = False
        elif word in value_flags:
            skip = True
        elif not word.startswith("-"):
            files.append(word)
    release = {
        "draft": True,
        "immutable": False,
        "assets": {},
        "prerelease": "--prerelease" in args,
        "verify_tag": "--verify-tag" in args,
    }
    state["release"] = release
    if files:  # gh makes a draft, uploads, then publishes - unless --draft was given
        add_assets(release, files)
    if "--draft" not in args:
        publish(release)
elif words == ["release", "upload"]:
    if args[2] != tag or release is None:
        fail("release not found")
    add_assets(release, [a for a in args[3:] if not a.startswith("--")])
elif words == ["release", "edit"]:
    if args[2] != tag or release is None:
        fail("release not found")
    if args[3:] != ["--draft=false"]:
        fail("fake gh: unsupported edit: " + " ".join(args), 2)
    publish(release)
elif words == ["release", "verify"]:
    if args[2:] != [tag] or release is None or not release["immutable"]:
        fail("no attestations for tag " + tag)
    state["verify_calls"] += 1
    save()
    if state["verify_calls"] <= state["verify_fails_first"]:
        fail("no attestations for tag " + tag + " (not generated yet)")
elif words == ["attestation", "verify"]:
    path = args[2]
    wanted = {
        "--bundle": None,
        "--repo": state["repository"],
        "--signer-workflow": state["repository"] + "/.github/workflows/release.yml",
    }
    given = {a: args[i + 1] for i, a in enumerate(args) if a in wanted and i + 1 < len(args)}
    if set(given) != set(wanted) or len(args) != 9:
        fail("fake gh: gh attestation verify needs exactly --bundle/--repo/--signer-workflow", 2)
    for flag, expected in wanted.items():
        if expected is not None and given[flag] != expected:
            fail("verification failed: " + flag + " " + given[flag] + " != " + expected)
    if not Path(path).is_file() or not Path(given["--bundle"]).is_file():
        fail("failed to open local artifact or bundle")
    if hashlib.sha256(Path(given["--bundle"]).read_bytes()).hexdigest() != state["bundle_sha256"]:
        fail("verification failed: this is not the bundle that actions/attest wrote")
    if digest(path) not in state["subjects"]:
        fail("verification failed: the file is not a subject of the attestation")
    if state["attest_verify_fails"]:
        fail("verification failed: no matching attestation")
else:
    fail("fake gh: unsupported call: " + " ".join(args), 2)
save()
"""

#: Always instant: the job sleeps while it waits for the release attestation.
FAKE_SLEEP = "#!/bin/sh\nexit 0\n"
#: A host without ``sha256sum`` (some macOS setups) still has ``shasum``.
SHA256SUM_SHIM = '#!/bin/sh\nexec shasum -a 256 "$@"\n'

BUNDLE_BYTES = b'{"mediaType":"application/vnd.dev.sigstore.bundle.v0.3+json"}\n'

needs_bash_and_jq = pytest.mark.skipif(
    sys.platform == "win32"
    or shutil.which("bash") is None
    or shutil.which("jq") is None,
    reason="the release scripts need bash and jq (both are on the GitHub runner)",
)


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _local_files(tag: str) -> dict[str, bytes]:
    version = tag.removeprefix("v")
    return {
        f"dist/ai_intervention_agent-{version}-py3-none-any.whl": b"wheel bytes",
        f"dist/ai_intervention_agent-{version}.tar.gz": b"sdist bytes",
        f"vsix/ai-intervention-agent-{version}.vsix": b"vsix bytes",
    }


def _bundle_name(tag: str) -> str:
    return f"ai-intervention-agent-{tag.removeprefix('v')}.sigstore.json"


def _published(*, immutable: bool) -> dict[str, Any]:
    """A Release that already went out with exactly what the job would ship."""
    assets = {
        Path(path).name: {"digest": _sha(data), "size": len(data)}
        for path, data in _local_files(TAG).items()
    }
    assets[_bundle_name(TAG)] = {
        "digest": _sha(BUNDLE_BYTES),
        "size": len(BUNDLE_BYTES),
    }
    return {
        "draft": False,
        "immutable": immutable,
        "assets": assets,
        "prerelease": False,
    }


def _draft() -> dict[str, Any]:
    return {
        "draft": True,
        "immutable": False,
        "assets": {"half.whl": {}},
        "prerelease": False,
    }


@dataclass
class Outcome:
    code: int
    ran: list[str]
    out: str
    calls: list[list[str]]
    release: dict[str, Any] | None
    verify_calls: int

    def calls_of(self, *words: str) -> list[list[str]]:
        return [call for call in self.calls if call[: len(words)] == list(words)]

    @property
    def verbs(self) -> list[str]:
        """Every call that changes a Release, in order: ``create``, ``upload``, ``edit``."""
        return [
            call[1]
            for call in self.calls
            if call[0] == "release" and call[1] in {"create", "upload", "edit"}
        ]

    @property
    def changed_nothing(self) -> bool:
        return self.verbs == [] and self.calls_of("attestation") == []


class Sim:
    """Runs the job's three scripted steps in workflow order, as ``bash -e`` would in Actions."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.count = 0
        self.bin = root / "bin"
        self.bin.mkdir()
        script = self.bin / "gh.py"
        script.write_text(FAKE_GH, encoding="utf-8")
        self._tool(
            "gh",
            f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(script))} "$@"\n',
        )
        self._tool("sleep", FAKE_SLEEP)
        if shutil.which("sha256sum") is None:
            self._tool("sha256sum", SHA256SUM_SHIM)

    def _tool(self, name: str, source: str) -> None:
        path = self.bin / name
        path.write_text(source, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def run(
        self,
        *,
        release: dict[str, Any] | None = None,
        tag: str = TAG,
        immutable_setting: bool = True,
        release_script: str | None = None,
        **faults: Any,
    ) -> Outcome:
        """One run of the job; *release* is the Release the tag already has.

        With *release_script* only that script runs, as the job's whole release step (used for
        the step the job had before R879).  *faults* are the fake's switches (see ``state``).
        """
        self.count += 1
        work = self.root / f"run{self.count}"
        work.mkdir()
        files = _local_files(tag)
        for rel, data in files.items():
            (work / rel).parent.mkdir(parents=True, exist_ok=True)
            (work / rel).write_bytes(data)
        attest_bundle = work / "runner-temp" / "attestation.json"
        attest_bundle.parent.mkdir()
        attest_bundle.write_bytes(BUNDLE_BYTES)
        state: dict[str, Any] = {
            "tag": tag,
            "repository": REPOSITORY,
            "release": release,
            "immutable_setting": immutable_setting,
            "bundle_sha256": hashlib.sha256(BUNDLE_BYTES).hexdigest(),
            "subjects": [_sha(data) for data in files.values()],
            "corrupt_upload": False,
            "verify_fails_first": 0,
            "attest_verify_fails": False,
            "view_fails_after_publish": False,
            "verify_calls": 0,
        }
        assert set(faults) <= set(state), f"unknown fault {set(faults) - set(state)}"
        state.update(faults)
        (work / "state.json").write_text(json.dumps(state))
        log = work / "gh.log"
        log.write_text("")
        output = work / "github_output"
        output.write_text("")
        expressions = {
            "secrets.GITHUB_TOKEN": "token-from-the-job",
            "steps.attest.outputs.bundle-path": str(attest_bundle),
        }
        base_env = {
            "PATH": os.pathsep.join(
                [str(self.bin), os.environ.get("PATH", "/usr/bin:/bin")]
            ),
            "HOME": str(work),
            "GITHUB_REF_NAME": tag,
            "GITHUB_REPOSITORY": REPOSITORY,
            "GITHUB_OUTPUT": str(output),
            "FAKE_GH_STATE": str(work / "state.json"),
            "FAKE_GH_LOG": str(log),
        }
        ran: list[str] = []
        out = ""
        code = 0
        for key, step in self._steps(release_script):
            if "if" in step:
                assert step["if"] == GATE, f"unexpected condition {step['if']!r}"
                answers = dict(
                    line.split("=", 1)
                    for line in output.read_text().splitlines()
                    if "=" in line
                )
                if answers.get("state") != "none":
                    continue
            env = dict(base_env)
            for name, value in (step.get("env") or {}).items():
                env[name] = re.sub(
                    r"\$\{\{\s*(.*?)\s*\}\}",
                    lambda m: expressions[m.group(1)],
                    str(value),
                )
            (work / "step.sh").write_text(step["run"], encoding="utf-8")
            done = subprocess.run(
                ["bash", "-e", "step.sh"],
                cwd=work,
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            ran.append(key)
            out += done.stdout + done.stderr
            code = done.returncode
            if code != 0:
                break
        final = json.loads((work / "state.json").read_text())
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        return Outcome(code, ran, out, calls, final["release"], final["verify_calls"])

    @staticmethod
    def _steps(release_script: str | None) -> list[tuple[str, dict[str, Any]]]:
        """The scripted steps in workflow order (the order itself is pinned by a static test)."""
        if (
            release_script is not None
        ):  # the step as it was before R879: no gate, same token
            env = {"GITHUB_TOKEN": "${{ secrets.GITHUB_TOKEN }}"}
            return [("release", {"run": release_script, "env": env})]
        return [
            ("state", _state_step()),
            ("bundle", _bundle_step()),
            ("release", _release_step()),
        ]


@pytest.fixture
def sim(tmp_path: Path) -> Sim:
    return Sim(tmp_path)


@needs_bash_and_jq
def test_a_new_release_is_drafted_filled_checked_then_published(sim: Sim) -> None:
    done = sim.run(release=None, immutable_setting=True)
    assert done.code == 0, done.out
    assert done.ran == ["state", "bundle", "release"]
    assert done.verbs == ["create", "upload", "edit"]
    create = done.calls_of("release", "create")[0]
    assert create[:3] == ["release", "create", TAG], "no file goes to `create`"
    assert set(create[3:]) == {
        "--draft",
        "--verify-tag",
        "--title",
        TAG,
        "--generate-notes",
    }
    assert done.calls_of("release", "edit") == [
        ["release", "edit", TAG, "--draft=false"]
    ]
    # four files, byte for byte what is on disk (the digests are those of the local files)
    expected = {Path(path).name: _sha(data) for path, data in _local_files(TAG).items()}
    expected[_bundle_name(TAG)] = _sha(BUNDLE_BYTES)
    assert done.release is not None
    assert {n: a["digest"] for n, a in done.release["assets"].items()} == expected
    assert done.release["draft"] is False and done.release["immutable"] is True
    assert done.release["verify_tag"] is True and done.release["prerelease"] is False
    # every shipped file was checked against the bundle (the fake pins the flags and the bundle)
    checked = sorted(
        Path(call[2]).name for call in done.calls_of("attestation", "verify")
    )
    assert checked == sorted(Path(path).name for path in _local_files(TAG))
    assert "::warning::" not in done.out and "::error::" not in done.out


@needs_bash_and_jq
def test_the_notes_after_the_publish_are_notices_only(sim: Sim) -> None:
    on = sim.run(immutable_setting=True)
    off = sim.run(immutable_setting=False)
    assert on.code == off.code == 0
    assert on.release is not None and on.release["immutable"] is True
    assert off.release is not None and off.release["immutable"] is False
    assert on.calls_of("release", "verify") != []
    assert off.calls_of("release", "verify") == [], (
        "nothing to wait for on a mutable Release"
    )
    for done in (on, off):
        assert "::notice::" in done.out
        assert "::warning::" not in done.out and "::error::" not in done.out


@needs_bash_and_jq
def test_a_leftover_draft_stops_the_job_before_it_touches_anything(sim: Sim) -> None:
    done = sim.run(release=_draft())
    assert done.code == 1
    assert done.ran == ["state"]
    assert done.changed_nothing
    assert "::error::" in done.out and TAG in done.out


@needs_bash_and_jq
@pytest.mark.parametrize("immutable", [True, False])
def test_a_rerun_after_the_release_went_out_changes_nothing_and_still_succeeds(
    sim: Sim, immutable: bool
) -> None:
    before = _published(immutable=immutable)
    done = sim.run(release=copy.deepcopy(before), immutable_setting=immutable)
    assert done.code == 0, done.out
    assert done.ran == ["state"], (
        "the attestation, the upload and the publish are skipped"
    )
    assert done.changed_nothing
    assert done.release == before
    assert "::notice::" in done.out


@needs_bash_and_jq
def test_a_wrong_upload_is_found_while_the_release_is_still_a_draft(sim: Sim) -> None:
    done = sim.run(corrupt_upload=True)
    assert done.code == 1
    assert done.verbs == ["create", "upload"], "the publish must not happen"
    assert done.release is not None and done.release["draft"] is True
    assert "::error::" in done.out and TAG in done.out


@needs_bash_and_jq
def test_a_bundle_that_fails_to_verify_stops_the_job_early(sim: Sim) -> None:
    done = sim.run(attest_verify_fails=True)
    assert done.code == 1
    assert done.ran == ["state", "bundle"]
    assert done.verbs == []
    assert done.release is None


@needs_bash_and_jq
def test_a_prerelease_tag_makes_a_prerelease_and_names_its_bundle(sim: Sim) -> None:
    tag = "v1.9.0-rc1"
    done = sim.run(tag=tag)
    assert done.code == 0, done.out
    assert done.release is not None and done.release["prerelease"] is True
    assert _bundle_name(tag) in done.release["assets"]
    assert "--prerelease" in done.calls_of("release", "create")[0]


@needs_bash_and_jq
def test_a_slow_release_attestation_is_waited_for_but_not_required(sim: Sim) -> None:
    slow = sim.run(verify_fails_first=2)
    never = sim.run(verify_fails_first=99)
    assert slow.code == never.code == 0
    assert slow.verify_calls == 3, "asked until the attestation showed up"
    assert never.verify_calls == 6, "asked six times, 5 s apart, then let it be"
    for done in (slow, never):
        assert "::warning::" not in done.out and "::error::" not in done.out


@needs_bash_and_jq
def test_a_failed_read_after_the_publish_does_not_fail_the_job(sim: Sim) -> None:
    done = sim.run(view_fails_after_publish=True)
    assert done.code == 0, done.out
    assert done.release is not None and done.release["draft"] is False
    assert "::warning::" not in done.out and "::error::" not in done.out


# ---------------------------------------------------------------------------------------------
# What the old step did (the reason for all of the above)
# ---------------------------------------------------------------------------------------------


@needs_bash_and_jq
def test_the_old_step_failed_a_rerun_on_an_immutable_release(sim: Sim) -> None:
    done = sim.run(release=_published(immutable=True), release_script=OLD_RELEASE_STEP)
    assert done.code != 0
    assert "--clobber" in done.calls_of("release", "upload")[0]
    assert "immutable" in done.out


@needs_bash_and_jq
def test_the_old_step_swapped_the_files_of_a_mutable_release(sim: Sim) -> None:
    before = _published(immutable=False)
    wheel = next(name for name in before["assets"] if name.endswith(".whl"))
    before["assets"][wheel]["digest"] = "sha256:" + "1" * 64  # as if rebuilt since
    done = sim.run(
        release=copy.deepcopy(before),
        immutable_setting=False,
        release_script=OLD_RELEASE_STEP,
    )
    assert done.code == 0
    assert done.release is not None
    assert done.release["assets"][wheel]["digest"] != before["assets"][wheel]["digest"]


@needs_bash_and_jq
def test_the_old_step_ended_green_with_a_draft_still_unpublished(sim: Sim) -> None:
    done = sim.run(release=_draft(), release_script=OLD_RELEASE_STEP)
    assert done.code == 0
    assert done.release is not None and done.release["draft"] is True
    assert done.calls_of("release", "edit") == []


# ---------------------------------------------------------------------------------------------
# The fake is not a pushover
# ---------------------------------------------------------------------------------------------


@needs_bash_and_jq
def test_the_fake_gh_refuses_what_github_refuses(sim: Sim, tmp_path: Path) -> None:
    """If it let these through, the scenarios above would prove nothing."""
    work = tmp_path / "fake-self-test"
    work.mkdir()
    (work / "a.whl").write_bytes(b"x")

    def call(
        release: dict[str, Any] | None, *args: str, token: bool = True
    ) -> subprocess.CompletedProcess[str]:
        state = {
            "tag": TAG,
            "repository": REPOSITORY,
            "release": release,
            "immutable_setting": True,
            "bundle_sha256": "",
            "subjects": [],
            "corrupt_upload": False,
            "verify_fails_first": 0,
            "attest_verify_fails": False,
            "view_fails_after_publish": False,
            "verify_calls": 0,
        }
        (work / "s.json").write_text(json.dumps(state))
        env = {
            "PATH": os.environ.get("PATH", ""),
            "FAKE_GH_STATE": str(work / "s.json"),
            "FAKE_GH_LOG": str(work / "log"),
        }
        if token:
            env["GITHUB_TOKEN"] = "t"
        return subprocess.run(
            [str(sim.bin / "gh"), *args],
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    immutable = _published(immutable=True)
    assert call(immutable, "release", "upload", TAG, "a.whl").returncode == 1
    assert (
        call(immutable, "release", "upload", TAG, "a.whl", "--clobber").returncode == 1
    )
    assert call(immutable, "release", "create", TAG).returncode == 1
    assert call(None, "release", "create", TAG, "--draft", token=False).returncode == 4
    assert call(None, "release", "create", TAG, "--draft").returncode == 0
    assert (
        call(None, "attestation", "verify", "a.whl", "--bundle", "a.whl").returncode
        == 2
    )
    assert call(None, "release", "list").returncode == 2
