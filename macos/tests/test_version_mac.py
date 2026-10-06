"""The running version of a Mac release is its release tag (version_mac),
not the unstamped client/version.py of the tag's checkout."""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(ROOT, "macos"), os.path.join(ROOT, "client"), os.path.join(ROOT, ".pydeps")]

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS layer")

import version  # noqa: E402
from winzapp_mac import updater_mac as um, version_mac  # noqa: E402

PLACEHOLDER = "2.1.0.0"
TAGGED = {"WinZappReleaseTag": "v2.1.0.4050alpha"}


@pytest.fixture
def unstamped(monkeypatch):
    monkeypatch.setattr(version, "__version__", PLACEHOLDER)
    monkeypatch.setattr(sys, "frozen", True, raising=False)


def test_a_release_build_runs_as_its_tag(monkeypatch, unstamped):
    monkeypatch.setattr(um, "_info", lambda: TAGGED)
    version_mac.install()
    assert version.__version__ == "2.1.0.4050alpha"


def test_the_updater_no_longer_offers_the_running_release(monkeypatch, unstamped):
    """The bug: UpdateChecker compares the latest release against
    version.__version__, so an unstamped 2.1.0.0 saw its own release as
    newer on every check."""
    import updater
    monkeypatch.setattr(um, "_info", lambda: TAGGED)
    assert updater.is_newer("2.1.0.4050alpha", version.__version__)
    version_mac.install()
    assert not updater.is_newer("2.1.0.4050alpha", version.__version__)


@pytest.mark.parametrize("info", [{}, {"WinZappReleaseTag": ""},
                                  {"WinZappReleaseTag": "2.1.0.5"},
                                  {"WinZappReleaseTag": "not a tag"}])
def test_a_build_without_a_valid_tag_keeps_version_py(monkeypatch, unstamped, info):
    monkeypatch.setattr(um, "_info", lambda: info)
    version_mac.install()
    assert version.__version__ == PLACEHOLDER


def test_running_from_source_keeps_version_py(monkeypatch, unstamped):
    monkeypatch.delattr(sys, "frozen")
    monkeypatch.setattr(um, "_info", lambda: TAGGED)
    version_mac.install()
    assert version.__version__ == PLACEHOLDER


def test_installed_before_the_modules_that_copy_the_version():
    """`from version import __version__` binds a copy at import, so the
    swap must come right after paths_mac, before any install() that imports
    WinZapp modules."""
    path = os.path.join(ROOT, "macos", "winzapp_mac", "__init__.py")
    with open(path, encoding="utf-8") as fh:
        calls = [line.split("(")[0].strip() for line in fh if ".install()" in line]
    assert calls[:2] == ["paths_mac.install", "version_mac.install"]
