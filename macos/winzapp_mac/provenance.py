"""Commit provenance of a macOS release: is this build tied to a commit of
WinZapp's own repository?

The Mac releases are published from another repository (Info.plist
WinZappMacReleasesRepo), so the Apple signature only says "the Mac
maintainer's Apple team signed this", never "this code went through
gabrielhhaber/WinZapp_Python". Each Mac release therefore carries a
provenance file, and the updater checks it against the OFFICIAL repository
before installing. Pure standard library on purpose: no PyObjC, no wx, so the
normal Windows `pytest` exercises it and macos/build_app.py (which runs
before any dependency is installed) can use it too.

Threat model
  Attacker: whoever controls the releases repository (a fork, its CI secrets,
  its release assets) and can publish any zip and any provenance there.
  Cannot: push a tag to the official repository, or make api.github.com
  answer for it. The official repository's write access is the trust root the
  Windows releases already rely on.
  Goal: a Mac update that contains code which never went through our repo
  must not install.

What is verified (in this order, every step fails closed)
  1. The provenance file is well formed: exact keys, schema 1, source_repo is
     the pinned official repository, source_commit 40 lowercase hex, version a
     release tag, artifacts a small name -> sha256 map.
  2. Its version is the tag of the release being installed (no replaying the
     provenance of another release) and is newer than the running version.
  3. Over HTTPS, no redirects, against api.github.com/repos/<OFFICIAL_REPO>
     only: the tag exists in the official repository and, peeled through
     annotated tag objects, points at exactly source_commit.
  4. The downloaded zip's sha256 equals artifacts[<zip name>].

Why the tag, and not "the commit exists in our repo"
  GitHub serves a fork's commits through the parent repository
  (/repos/<parent>/commits/<sha> answers 200 for them), so existence proves
  nothing. A tag can only be created in the official repository by someone
  with write access to it, which a fork's owner does not have. A compare
  against the default branch would additionally prove "reachable from main",
  but it costs another API call (the unauthenticated limit is 60 an hour) and
  would refuse a legitimate hotfix tag on another branch; the tag is already
  the maintainer's explicit act, so it is the check used.

What this does NOT prove
  That the zip was built from that commit. The releaser can build from a
  modified tree and name an honest commit. build_app.py refuses a dirty tree
  and a HEAD that is not the tag, but that runs on the releaser's machine.
  Only a reproducible build or a CI attestation checked by the updater
  (docs/reference/macos.md, "Commit provenance") would prove it. Tags can
  also be moved by someone with write access; protect them (tag ruleset).
"""

import hashlib
import json
import re
import urllib.error
import urllib.request

# Pinned here: not read from the plist, not from the provenance file.
OFFICIAL_REPO = "gabrielhhaber/WinZapp_Python"
API_HOST = "api.github.com"
SCHEMA = 1
SOURCE_COMMIT_KEY = "WinZappSourceCommit"      # Info.plist, written by build_app.py

MAX_PROVENANCE_BYTES = 16 * 1024
MAX_API_BYTES = 256 * 1024
TIMEOUT = 15
MAX_ARTIFACTS = 8
MAX_TAG_DEPTH = 4                              # annotated tag -> tag -> ... -> commit

_KEYS = {"schema", "version", "source_repo", "source_commit", "artifacts"}
_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TAG = re.compile(r"^v(\d{1,9})\.(\d{1,9})\.(\d{1,9})\.(\d{1,9})(alpha|beta)?$")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_PRE = {"alpha": 1, "beta": 2, "": 3}


class ProvenanceError(Exception):
    """Anything that stops a release from being verified."""


def provenance_name(arch):
    """One file per architecture, so the two build jobs never have to merge
    or overwrite a shared one."""
    return f"WinZapp-macOS-provenance-{arch}.json"


def is_commit(value):
    return isinstance(value, str) and bool(_SHA1.match(value))


def is_release_tag(value):
    return isinstance(value, str) and bool(_TAG.match(value))


def _tag_key(tag):
    m = _TAG.match(tag)
    return tuple(int(m.group(i)) for i in range(1, 5)), _PRE[m.group(5) or ""]


def tag_is_newer(tag, running_version):
    """Is release *tag* strictly newer than *running_version* ("2.0.0.5" or
    "2.0.0.5alpha")? An unparseable version is never newer."""
    candidate = "v" + str(running_version or "").lstrip("vV")
    if not is_release_tag(tag) or not is_release_tag(candidate):
        return False
    return _tag_key(tag) > _tag_key(candidate)


# -- the file -------------------------------------------------------------------

def parse_provenance(raw):
    """The validated provenance dict, or ProvenanceError."""
    if not isinstance(raw, (bytes, bytearray)) or len(raw) > MAX_PROVENANCE_BYTES:
        raise ProvenanceError("provenance file missing or too large")
    try:
        data = json.loads(bytes(raw).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise ProvenanceError("provenance file is not valid JSON")
    if not isinstance(data, dict) or set(data) != _KEYS:
        raise ProvenanceError("provenance file has unexpected fields")
    if data["schema"] != SCHEMA or isinstance(data["schema"], bool):
        raise ProvenanceError("provenance schema is not supported")
    if data["source_repo"] != OFFICIAL_REPO:
        raise ProvenanceError("provenance names a different source repository")
    if not is_commit(data["source_commit"]):
        raise ProvenanceError("provenance source_commit is not a full commit id")
    if not is_release_tag(data["version"]):
        raise ProvenanceError("provenance version is not a release tag")
    arts = data["artifacts"]
    if not isinstance(arts, dict) or not 1 <= len(arts) <= MAX_ARTIFACTS:
        raise ProvenanceError("provenance artifacts are malformed")
    for name, digest in arts.items():
        if not (isinstance(name, str) and _NAME.match(name)
                and isinstance(digest, str) and _SHA256.match(digest)):
            raise ProvenanceError("provenance artifacts are malformed")
    return data


def build_provenance(tag, commit, artifacts):
    """The JSON bytes build_app.py writes next to the zip."""
    data = {"schema": SCHEMA, "version": tag, "source_repo": OFFICIAL_REPO,
            "source_commit": commit, "artifacts": dict(artifacts)}
    raw = (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")
    parse_provenance(raw)                       # never emit what the updater would refuse
    return raw


# -- the official repository ----------------------------------------------------

def _api(path):
    return f"https://{API_HOST}/repos/{OFFICIAL_REPO}/{path}"


def _json(fetch, url):
    try:
        data = json.loads(fetch(url).decode("utf-8"))
    except ProvenanceError:
        raise
    except Exception as exc:
        raise ProvenanceError(f"unreadable answer from {API_HOST}: {type(exc).__name__}")
    if not isinstance(data, dict):
        raise ProvenanceError(f"unexpected answer from {API_HOST}")
    return data


def _object(data):
    obj = data.get("object")
    if (not isinstance(obj, dict) or obj.get("type") not in ("commit", "tag")
            or not is_commit(obj.get("sha"))):
        raise ProvenanceError("unexpected object in the tag answer")
    return obj["type"], obj["sha"]


def resolve_official_tag(tag, fetch):
    """The commit our repository's tag *tag* points at (annotated tags
    peeled), or ProvenanceError when the tag is missing or odd. *fetch(url)*
    returns the body bytes or raises."""
    if not is_release_tag(tag):
        raise ProvenanceError("not a release tag")
    ref = _json(fetch, _api(f"git/ref/tags/{tag}"))
    if ref.get("ref") != f"refs/tags/{tag}":
        raise ProvenanceError("the official repository has no such tag")
    kind, sha = _object(ref)
    for _ in range(MAX_TAG_DEPTH):
        if kind == "commit":
            return sha
        tag_obj = _json(fetch, _api(f"git/tags/{sha}"))
        if tag_obj.get("sha") != sha:
            raise ProvenanceError("tag object answer does not match the request")
        kind, sha = _object(tag_obj)
    raise ProvenanceError("tag chain is too deep")


def resolve_build_source(git, fetch, tag_hint=""):
    """Build time (macos/build_app.py): (tag, commit) when HEAD is exactly the
    commit our repository's release tag points at, None for an untagged
    development build (no provenance is made, and no updater accepts such a
    build). Raises ProvenanceError for a tag that does not hold: a different
    HEAD, uncommitted changes to tracked files, a tag we do not have.

    *git(*args)* returns git's stdout stripped, raising on failure; *tag_hint*
    is the tag a CI checkout names (it may not have fetched tags). Untracked
    files are not looked at: this is a guard for an honest releaser, not a
    proof (see the module docstring)."""
    tag = tag_hint
    if not tag:
        try:
            tag = git("describe", "--exact-match", "--tags", "HEAD")
        except Exception:
            return None
    if not is_release_tag(tag):
        raise ProvenanceError(f"{tag!r} is not a release tag")
    head = git("rev-parse", "HEAD")
    if not is_commit(head):
        raise ProvenanceError("HEAD is not a full commit id")
    if git("status", "--porcelain", "--untracked-files=no"):
        raise ProvenanceError("tracked files differ from HEAD; build from a clean checkout")
    official = resolve_official_tag(tag, fetch)
    if official != head:
        raise ProvenanceError(
            f"HEAD is {head[:12]} but {OFFICIAL_REPO}'s {tag} is {official[:12]}")
    return tag, head


def verify_release(raw, tag, running_version, fetch, running_commit=""):
    """(ok, detail) before anything is downloaded: the provenance in *raw* is
    valid, belongs to release *tag*, is newer than *running_version*, and the
    official repository's tag points at its source_commit. Nothing raises."""
    try:
        data = parse_provenance(raw)
        if data["version"] != tag:
            raise ProvenanceError("provenance belongs to another release")
        if not tag_is_newer(tag, running_version):
            raise ProvenanceError("release is not newer than the running version")
        if running_commit and data["source_commit"] == running_commit:
            raise ProvenanceError("release is the commit already running")
        got = resolve_official_tag(tag, fetch)
        if got != data["source_commit"]:
            raise ProvenanceError(
                "the release tag in the official repository points at another commit")
    except ProvenanceError as exc:
        return False, f"could not verify commit provenance: {exc}"
    return True, "ok"


def check_artifact(raw, name, path):
    """(ok, detail): the file at *path* has the sha256 *raw*'s provenance lists
    for *name*."""
    try:
        want = parse_provenance(raw)["artifacts"].get(name)
        if not want:
            raise ProvenanceError(f"provenance does not list {name}")
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest() != want:
            raise ProvenanceError(f"{name} does not match its provenance hash")
    except (ProvenanceError, OSError) as exc:
        return False, f"could not verify commit provenance: {exc}"
    return True, "ok"


# -- HTTP -----------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None                             # surfaces as an HTTPError


class _HttpsRedirectOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.lower().startswith("https://"):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_API_OPENER = urllib.request.build_opener(_NoRedirect)
_ASSET_OPENER = urllib.request.build_opener(_HttpsRedirectOnly)


def _read(opener, url, limit, headers):
    req = urllib.request.Request(url, headers=dict(headers, **{"User-Agent": "WinZapp-macOS"}))
    try:
        with opener.open(req, timeout=TIMEOUT) as resp:
            if resp.status != 200:
                raise ProvenanceError(f"HTTP {resp.status}")
            if not resp.geturl().lower().startswith("https://"):
                raise ProvenanceError("answer did not come over HTTPS")
            body = resp.read(limit + 1)
            final = resp.geturl()
    except ProvenanceError:
        raise
    except urllib.error.HTTPError as exc:
        # 3xx lands here (redirects are refused); 403/429 is the rate limit.
        raise ProvenanceError(f"HTTP {exc.code}")
    except Exception as exc:
        raise ProvenanceError(f"request failed: {type(exc).__name__}")
    if len(body) > limit:
        raise ProvenanceError("answer is too large")
    return body, final


def fetch_official(url):
    """GET from the official API: https, api.github.com only, no redirect,
    size-capped, unauthenticated (no token is ever sent or logged)."""
    if not url.startswith(f"https://{API_HOST}/repos/{OFFICIAL_REPO}/"):
        raise ProvenanceError("refusing to ask anything but the official repository")
    body, final = _read(_API_OPENER, url, MAX_API_BYTES,
                        {"Accept": "application/vnd.github+json"})
    if final != url:
        raise ProvenanceError("answer came from another address")
    return body


def fetch_release_asset(url):
    """GET a release asset from the releases repository. Downloads redirect
    to GitHub's storage hosts, so https redirects are followed; the content
    is untrusted until verify_release() and check_artifact() pass."""
    if not url.startswith("https://github.com/"):
        raise ProvenanceError("release assets come from github.com")
    return _read(_ASSET_OPENER, url, MAX_PROVENANCE_BYTES, {})[0]
