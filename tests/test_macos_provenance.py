"""Commit provenance of the macOS updater (macos/winzapp_mac/provenance.py).

The module is pure standard library, so it is imported by path and tested on
every platform with a fake GitHub API; nothing here touches the network.
The attacker modelled is the owner of the releases repository: they control
the zip and the provenance file, and a fork's commits are reachable through
the official repository's /commits/<sha> API.
"""

import hashlib
import importlib.util
import io
import json
import pathlib
import urllib.error
import urllib.request

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_PATH = _ROOT / "macos" / "winzapp_mac" / "provenance.py"

pytestmark = pytest.mark.skipif(not _PATH.is_file(), reason="no macOS layer in this checkout")

_spec = importlib.util.spec_from_file_location("winzapp_provenance_under_test", _PATH)
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)

COMMIT = "a" * 40
OTHER = "b" * 40
TAG_OBJ = "c" * 40
TAG = "v2.0.0.5"
ZIP = "WinZapp-macOS-arm64.zip"
ZIP_BYTES = b"zip bytes"
ZIP_SHA = hashlib.sha256(ZIP_BYTES).hexdigest()


def _prov(**over):
    data = {"schema": 1, "version": TAG, "source_repo": P.OFFICIAL_REPO,
            "source_commit": COMMIT, "artifacts": {ZIP: ZIP_SHA}}
    data.update(over)
    return json.dumps(data).encode()


class Api:
    """The official repository's API: refs and tag objects by url."""

    def __init__(self, tags=None, tag_objects=None):
        self.tags = tags if tags is not None else {TAG: ("commit", COMMIT)}
        self.tag_objects = tag_objects or {}
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        base = f"https://api.github.com/repos/{P.OFFICIAL_REPO}/"
        assert url.startswith(base)
        path = url[len(base):]
        if path.startswith("git/ref/tags/"):
            tag = path.rsplit("/", 1)[1]
            if tag not in self.tags:
                raise P.ProvenanceError("HTTP 404")
            kind, sha = self.tags[tag]
            return json.dumps({"ref": f"refs/tags/{tag}", "object": {"type": kind, "sha": sha}}).encode()
        if path.startswith("git/tags/"):
            sha = path.rsplit("/", 1)[1]
            kind, target = self.tag_objects[sha]
            return json.dumps({"sha": sha, "object": {"type": kind, "sha": target}}).encode()
        raise AssertionError(url)


def _verify(raw=None, tag=TAG, running="2.0.0.4", api=None, **kw):
    return P.verify_release(raw if raw is not None else _prov(), tag, running,
                            api or Api(), **kw)


# -- accepted -----------------------------------------------------------------

def test_a_valid_provenance_is_accepted():
    api = Api()
    assert _verify(api=api) == (True, "ok")
    assert api.urls == [f"https://api.github.com/repos/{P.OFFICIAL_REPO}/git/ref/tags/{TAG}"]


def test_an_annotated_tag_is_peeled_to_its_commit():
    api = Api(tags={TAG: ("tag", TAG_OBJ)}, tag_objects={TAG_OBJ: ("commit", COMMIT)})
    assert _verify(api=api)[0]


def test_a_tag_of_a_tag_is_peeled_and_a_chain_that_never_ends_is_refused():
    t2 = "d" * 40
    api = Api(tags={TAG: ("tag", TAG_OBJ)},
              tag_objects={TAG_OBJ: ("tag", t2), t2: ("commit", COMMIT)})
    assert _verify(api=api)[0]
    loop = Api(tags={TAG: ("tag", TAG_OBJ)}, tag_objects={TAG_OBJ: ("tag", TAG_OBJ)})
    assert not _verify(api=loop)[0]


def test_an_alpha_tag_is_a_release_like_any_other():
    tag = "v2.0.0.3895alpha"
    api = Api(tags={tag: ("commit", COMMIT)})
    assert _verify(_prov(version=tag), tag=tag, running="2.0.0.3894alpha", api=api)[0]


# -- the tag is the proof -----------------------------------------------------

def test_a_tag_that_points_elsewhere_is_refused():
    ok, detail = _verify(api=Api(tags={TAG: ("commit", OTHER)}))
    assert not ok and "another commit" in detail


def test_a_tag_missing_from_the_official_repository_is_refused():
    ok, detail = _verify(api=Api(tags={}))
    assert not ok and "404" in detail


def test_a_commit_that_only_exists_in_a_fork_is_refused():
    """The /commits/<sha> API answers 200 for a fork's commit; the verifier
    never asks it, and the tag (which a fork owner cannot create) decides."""
    class ForkApi(Api):
        def __call__(self, url):
            if "/commits/" in url or "/compare/" in url:
                return json.dumps({"sha": COMMIT}).encode()      # a fork commit "exists"
            return super().__call__(url)
    api = ForkApi(tags={})
    assert not _verify(api=api)[0]
    assert not any("/commits/" in u or "/compare/" in u for u in api.urls)
    # even if the official tag resolves to the real main commit
    assert not _verify(api=ForkApi(tags={TAG: ("commit", OTHER)}))[0]


def test_a_malformed_api_answer_fails_closed():
    for body in (b"not json", b"[]", b'{"ref": "refs/tags/v2.0.0.5"}',
                 json.dumps({"ref": "refs/tags/v9.9.9.9",
                             "object": {"type": "commit", "sha": COMMIT}}).encode(),
                 json.dumps({"ref": f"refs/tags/{TAG}",
                             "object": {"type": "commit", "sha": "ABC"}}).encode()):
        assert not _verify(api=lambda url, body=body: body)[0]


def test_api_errors_and_timeouts_fail_closed():
    def boom(url):
        raise TimeoutError("slow")
    ok, detail = _verify(api=boom)
    assert not ok and "could not verify" in detail

    def limited(url):
        raise P.ProvenanceError("HTTP 403")
    assert not _verify(api=limited)[0]


# -- the file, the version, the replay ----------------------------------------

def test_a_provenance_of_another_release_is_refused():
    ok, detail = _verify(_prov(version="v2.0.0.4"), tag=TAG)
    assert not ok and "another release" in detail


def test_a_stale_genuine_provenance_does_not_pass_as_a_newer_tag():
    """Version and commit of an older release, relabelled v2.0.0.6: the
    official tag v2.0.0.6 is a different commit."""
    api = Api(tags={"v2.0.0.4": ("commit", COMMIT), "v2.0.0.6": ("commit", OTHER)})
    assert not _verify(_prov(version="v2.0.0.6"), tag="v2.0.0.6", api=api)[0]


@pytest.mark.parametrize("running", ["2.0.0.5", "2.0.0.9", "garbage", ""])
def test_a_release_that_is_not_newer_is_refused(running):
    ok, detail = _verify(running=running)
    assert not ok


def test_an_alpha_is_older_than_its_stable():
    assert P.tag_is_newer("v2.0.0.5", "2.0.0.5alpha")
    assert not P.tag_is_newer("v2.0.0.5alpha", "2.0.0.5")
    assert P.tag_is_newer("v2.0.0.10", "2.0.0.9")


def test_the_commit_that_is_already_running_is_not_an_update():
    assert not _verify(running_commit=COMMIT)[0]
    assert _verify(running_commit=OTHER)[0]


@pytest.mark.parametrize("over", [
    {"schema": 2}, {"schema": True}, {"schema": "1"},
    {"source_repo": "rocco-labs/WinZapp_Python"},
    {"source_repo": "GabrielHHaber/WinZapp_Python"},
    {"source_commit": "A" * 40}, {"source_commit": "a" * 39}, {"source_commit": "main"},
    {"source_commit": None},
    {"version": "v2.0.0"}, {"version": "../v2.0.0.5"}, {"version": "v2.0.0.5/../x"},
    {"version": "v2.0.0.5dev"},
    {"artifacts": {}}, {"artifacts": []}, {"artifacts": {ZIP: "x" * 64}},
    {"artifacts": {ZIP: "A" * 64}}, {"artifacts": {"../evil": ZIP_SHA}},
    {"artifacts": {f"a{i}.zip": ZIP_SHA for i in range(P.MAX_ARTIFACTS + 1)}},
])
def test_an_invalid_provenance_is_refused(over):
    assert not _verify(_prov(**over))[0]


def test_unknown_missing_or_oversized_fields_are_refused():
    data = json.loads(_prov())
    assert not _verify(json.dumps({**data, "extra": 1}).encode())[0]
    data.pop("artifacts")
    assert not _verify(json.dumps(data).encode())[0]
    assert not _verify(b"x" * (P.MAX_PROVENANCE_BYTES + 1))[0]
    assert not _verify(b"\xff\xfe")[0]
    assert not _verify(b"[]")[0]


# -- the zip ------------------------------------------------------------------

def test_the_zip_must_match_its_provenance_hash(tmp_path):
    f = tmp_path / ZIP
    f.write_bytes(ZIP_BYTES)
    assert P.check_artifact(_prov(), ZIP, str(f)) == (True, "ok")
    f.write_bytes(ZIP_BYTES + b"!")
    assert not P.check_artifact(_prov(), ZIP, str(f))[0]
    assert not P.check_artifact(_prov(), "WinZapp-macOS-x86_64.zip", str(f))[0]
    assert not P.check_artifact(_prov(), ZIP, str(tmp_path / "missing"))[0]


def test_build_provenance_round_trips_and_refuses_what_the_updater_would():
    raw = P.build_provenance(TAG, COMMIT, {ZIP: ZIP_SHA})
    assert P.parse_provenance(raw)["source_commit"] == COMMIT
    with pytest.raises(P.ProvenanceError):
        P.build_provenance("main", COMMIT, {ZIP: ZIP_SHA})
    with pytest.raises(P.ProvenanceError):
        P.build_provenance(TAG, "abc", {ZIP: ZIP_SHA})


def test_one_provenance_file_per_architecture():
    assert P.provenance_name("arm64") != P.provenance_name("x86_64")


# -- the repository is pinned ---------------------------------------------------

def test_the_official_repository_is_pinned_in_the_code():
    assert P.OFFICIAL_REPO == "gabrielhhaber/WinZapp_Python"
    assert P.API_HOST == "api.github.com"


@pytest.mark.parametrize("url", [
    "https://api.github.com/repos/rocco-labs/WinZapp_Python/git/ref/tags/v1.0.0.1",
    "http://api.github.com/repos/gabrielhhaber/WinZapp_Python/git/ref/tags/v1.0.0.1",
    "https://evil.example/repos/gabrielhhaber/WinZapp_Python/x",
    "https://api.github.com.evil.example/repos/gabrielhhaber/WinZapp_Python/x",
    "https://api.github.com/repos/gabrielhhaber/WinZapp_Python2/x",
])
def test_the_official_fetcher_refuses_any_other_address(url):
    with pytest.raises(P.ProvenanceError):
        P.fetch_official(url)


def test_release_assets_only_from_github_com():
    for url in ("http://github.com/x", "https://evil.example/x", "https://github.com.evil/x"):
        with pytest.raises(P.ProvenanceError):
            P.fetch_release_asset(url)


# -- HTTP ---------------------------------------------------------------------

class FakeResponse(io.BytesIO):
    def __init__(self, body=b"{}", status=200, url=None):
        super().__init__(body)
        self.status, self._url = status, url

    def geturl(self):
        return self._url


class FakeOpener:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)

    def open(self, req, timeout=None):
        assert timeout and timeout <= 30
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        out._url = out._url or req.full_url
        return out


GOOD_URL = f"https://api.github.com/repos/{P.OFFICIAL_REPO}/git/ref/tags/{TAG}"


def test_the_api_fetcher_returns_the_body(monkeypatch):
    monkeypatch.setattr(P, "_API_OPENER", FakeOpener(FakeResponse(b"body")))
    assert P.fetch_official(GOOD_URL) == b"body"


def test_a_redirect_is_refused_not_followed():
    handler = P._NoRedirect()
    req = urllib.request.Request(GOOD_URL)
    assert handler.redirect_request(req, None, 302, "Found", {}, "https://evil.example/") is None


def test_a_redirect_to_another_host_is_refused(monkeypatch):
    monkeypatch.setattr(P, "_API_OPENER", FakeOpener(
        FakeResponse(b"{}", url="https://evil.example/repos/gabrielhhaber/WinZapp_Python/x")))
    with pytest.raises(P.ProvenanceError):
        P.fetch_official(GOOD_URL)
    monkeypatch.setattr(P, "_API_OPENER", FakeOpener(
        urllib.error.HTTPError(GOOD_URL, 302, "Found", {}, None)))
    with pytest.raises(P.ProvenanceError, match="302"):
        P.fetch_official(GOOD_URL)


def test_the_asset_redirect_handler_follows_https_only():
    handler = P._HttpsRedirectOnly()
    req = urllib.request.Request("https://github.com/a/b/releases/download/v1/x")
    assert handler.redirect_request(req, None, 302, "Found", {}, "http://objects.example/x") is None
    assert handler.redirect_request(req, None, 302, "Found", {}, "https://objects.example/x")


@pytest.mark.parametrize("outcome", [
    FakeResponse(b"{}", status=403), FakeResponse(b"{}", status=429),
    FakeResponse(b"x" * (P.MAX_API_BYTES + 1)),
    urllib.error.HTTPError(GOOD_URL, 403, "rate limited", {}, None),
    urllib.error.URLError("offline"), TimeoutError("slow"),
])
def test_http_failures_fail_closed(monkeypatch, outcome):
    monkeypatch.setattr(P, "_API_OPENER", FakeOpener(outcome))
    with pytest.raises(P.ProvenanceError):
        P.fetch_official(GOOD_URL)


def test_an_asset_larger_than_the_limit_is_refused(monkeypatch):
    monkeypatch.setattr(P, "_ASSET_OPENER", FakeOpener(FakeResponse(b"x" * (P.MAX_PROVENANCE_BYTES + 1))))
    with pytest.raises(P.ProvenanceError):
        P.fetch_release_asset("https://github.com/o/r/releases/download/v1.0.0.1/p.json")


# -- build time ---------------------------------------------------------------

def _git(head=COMMIT, describe=TAG, dirty=""):
    def git(*args):
        if args[0] == "describe":
            if describe is None:
                raise RuntimeError("no tag")
            return describe
        if args[0] == "rev-parse":
            return head
        if args[0] == "status":
            return dirty
        raise AssertionError(args)
    return git


def test_a_build_at_the_official_tag_gets_provenance():
    assert P.resolve_build_source(_git(), Api()) == (TAG, COMMIT)


def test_the_ci_tag_hint_is_used_when_git_has_no_tags():
    assert P.resolve_build_source(_git(describe=None), Api(), tag_hint=TAG) == (TAG, COMMIT)


def test_an_untagged_build_gets_no_provenance_and_asks_nothing():
    api = Api()
    assert P.resolve_build_source(_git(describe=None), api) is None
    assert api.urls == []


@pytest.mark.parametrize("git,api", [
    (_git(head=OTHER), Api()),                       # HEAD is not what the tag points at
    (_git(dirty=" M client/main.py"), Api()),        # modified tracked file
    (_git(), Api(tags={})),                          # tag not in the official repository
    (_git(describe="main"), Api()),                  # not a release tag
])
def test_a_tag_that_does_not_hold_stops_the_build(git, api):
    with pytest.raises(P.ProvenanceError):
        P.resolve_build_source(git, api)


# -- the updater uses it --------------------------------------------------------

def test_the_updater_verifies_before_downloading_and_the_hash_before_extracting():
    """updater_mac needs PyObjC and wx, so its order of steps is read from
    source here (macos/tests run on a Mac only)."""
    import ast
    src = (_ROOT / "macos" / "winzapp_mac" / "updater_mac.py").read_text(encoding="utf-8")
    work = next(n for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.FunctionDef) and n.name == "_work")
    calls = [ast.unparse(n.func) for n in ast.walk(work) if isinstance(n, ast.Call)]
    order = [calls.index(c) for c in ("self._provenance", "_download",
                                      "provenance.check_artifact", "verify_app")]
    assert order == sorted(order)
    assert 'enabled()' in src and "releases_repo(_info())" in src
    # the official repository is never taken from the plist or the provenance
    assert "OFFICIAL_REPO" not in src
