"""Self-updates for the macOS app.

WinZapp's UpdateChecker (client/updater.py) is reused as it is — release
selection across the stable and alpha channels, the "update available"
dialog with its changelog, the auto-update and alpha settings. Only where
the Mac differs is replaced:

* Releases come from the repository that publishes the macOS builds
  (Info.plist WinZappMacReleasesRepo, set by the release workflow), and the
  asset is WinZapp-macOS-<arch>.zip.
* Integrity: the zip must match the release's SHA256SUMS.txt, and the app
  inside must be signed by the same Apple Developer team as the running app
  and pass Gatekeeper (notarized). Gabriel's release keys cannot sign builds
  published elsewhere, so the Apple signature is what is trusted here.
* Installing: a small helper waits for WinZapp to quit, swaps the app bundle
  in place and opens the new one.

Only builds whose Info.plist names that repository (the signed release
builds) check for updates. Without it the updater is off: there is no
default repository to fall back to.
"""

import logging
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import threading

import wx

ARCH = platform.machine()   # arm64 / x86_64


def _bundle_path():
    exe = os.path.realpath(sys.executable)          # .../WinZapp.app/Contents/MacOS/WinZapp
    return os.path.dirname(os.path.dirname(os.path.dirname(exe)))


def _info():
    try:
        with open(os.path.join(_bundle_path(), "Contents", "Info.plist"), "rb") as fh:
            return plistlib.load(fh)
    except Exception:
        return {}


_REPO = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$")


def releases_repo(info):
    """The owner/name the Mac releases come from, or "" when the build
    names none (or something that is not a GitHub repository)."""
    repo = info.get("WinZappMacReleasesRepo")
    return repo if isinstance(repo, str) and _REPO.match(repo) else ""


def enabled():
    return bool(getattr(sys, "frozen", False) and releases_repo(_info()))


def asset_name():
    return f"WinZapp-macOS-{ARCH}.zip"


def find_zip_asset(assets):
    want = asset_name().lower()
    for asset in assets or []:
        if (asset.get("name") or "").lower() == want:
            return asset.get("browser_download_url", "")
    return ""


def team_id(app_path):
    r = subprocess.run(["codesign", "-dv", "--verbose=2", app_path], capture_output=True, text=True)
    for line in (r.stderr or "").splitlines():
        if line.startswith("TeamIdentifier="):
            value = line.split("=", 1)[1].strip()
            return None if value in ("", "not set") else value
    return None


def verify_app(new_app, running_app):
    """(ok, detail): same Developer team as the running app, intact
    signature, and accepted by Gatekeeper (notarized)."""
    expected = team_id(running_app)
    if not expected:
        return False, "the running app has no Developer ID signature to compare against"
    got = team_id(new_app)
    if got != expected:
        return False, f"signed by team {got!r}, expected {expected!r}"
    r = subprocess.run(["codesign", "--verify", "--deep", "--strict", new_app],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return False, "signature check failed: " + (r.stderr or "").strip()[-300:]
    r = subprocess.run(["spctl", "--assess", "--type", "execute", new_app],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return False, "Gatekeeper rejected it: " + (r.stderr or "").strip()[-300:]
    return True, "ok"


_SWAP_SCRIPT = """#!/bin/sh
# Wait for WinZapp (pid $1) to quit, put the new app in place, open it.
while kill -0 "$1" 2>/dev/null; do sleep 0.5; done
rm -rf "$3.old"
mv "$3" "$3.old" && mv "$2" "$3" && rm -rf "$3.old"
open "$3"
"""


def _download(url, dest, progress):
    import requests
    with requests.get(url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length") or 0)
        done = 0
        with open(dest, "wb") as fh:
            for chunk in resp.iter_content(1 << 20):
                fh.write(chunk)
                done += len(chunk)
                if total:
                    progress(int(done * 100 / total))


class MacUpdateProgress(wx.Dialog):
    """Download, verify and install, with its state in plain text and
    spoken through WinZapp's own speech at each stage."""

    def __init__(self, main_window, version, zip_url, sha256sums_url):
        i18n = main_window.i18n
        super().__init__(main_window, title=i18n.t("update_available_title"))
        self._mw, self._version = main_window, version
        self._zip_url, self._sums_url = zip_url, sha256sums_url
        self.installed = False
        sizer = wx.BoxSizer(wx.VERTICAL)
        self._status = wx.StaticText(self, label=version)
        self._gauge = wx.Gauge(self, range=100)
        sizer.Add(self._status, 0, wx.ALL | wx.EXPAND, 10)
        sizer.Add(self._gauge, 0, wx.ALL | wx.EXPAND, 10)
        self.SetSizerAndFit(sizer)
        self._last_spoken = -1
        threading.Thread(target=self._work, daemon=True).start()

    def _say(self, text):
        def ui():
            self._status.SetLabel(text)
            try:
                self._mw.output(text)
            except Exception:
                pass
        wx.CallAfter(ui)

    def _progress(self, pct):
        wx.CallAfter(self._gauge.SetValue, pct)
        if pct // 25 != self._last_spoken:
            self._last_spoken = pct // 25
            self._say(f"{pct}%")

    def _fail(self, detail):
        logging.error("[updater_mac] update to %s failed: %s", self._version, detail)
        i18n = self._mw.i18n

        def ui():
            wx.MessageBox(f"{i18n.t('error').format(app_name='WinZapp')}\n\n{detail}",
                          i18n.t("update_available_title"), wx.OK | wx.ICON_ERROR, self)
            self.EndModal(wx.ID_CANCEL)
        wx.CallAfter(ui)

    def _work(self):
        from updater import _verify_sha256sums
        work = tempfile.mkdtemp(prefix="winzapp-update-")
        try:
            zpath = os.path.join(work, asset_name())
            _download(self._zip_url, zpath, self._progress)
            ok, detail = _verify_sha256sums(zpath, asset_name(), self._sums_url,
                                            stable_keys=(), alpha_keys=())
            if not ok or not self._sums_url:
                return self._fail(detail if not ok else "the release has no SHA256SUMS.txt")
            subprocess.run(["ditto", "-x", "-k", zpath, work], check=True)
            new_app = os.path.join(work, "WinZapp.app")
            running = _bundle_path()
            ok, detail = verify_app(new_app, running)
            if not ok:
                return self._fail(detail)
            staged = running + ".update"
            if os.path.exists(staged):
                shutil.rmtree(staged)
            subprocess.run(["ditto", new_app, staged], check=True)
            script = os.path.join(work, "swap.sh")
            with open(script, "w") as fh:
                fh.write(_SWAP_SCRIPT)
            os.chmod(script, 0o755)
            subprocess.Popen([script, str(os.getpid()), staged, running],
                             start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.installed = True
            wx.CallAfter(self.EndModal, wx.ID_OK)
        except Exception as exc:
            self._fail(str(exc))


def _do_install(self, new_version, zip_url, sha256sums_url="", signature_url="", is_alpha=False):
    dlg = MacUpdateProgress(self._mw, new_version, zip_url, sha256sums_url)
    dlg.ShowModal()
    installed = dlg.installed
    dlg.Destroy()
    if installed:
        logging.info("[updater_mac] %s staged — quitting so it can be installed", new_version)
        wx.CallAfter(self._mw.quit_all_accounts)


def install():
    """Point WinZapp's own updater at the Mac releases (menubar_mac leaves
    it on only when enabled() is true)."""
    if not enabled():
        return
    repo = releases_repo(_info())
    import config
    import updater
    base = f"https://api.github.com/repos/{repo}/releases"
    for mod in (config, updater):
        mod.GITHUB_API_LATEST_RELEASE = base
        mod.GITHUB_API_LATEST_STABLE_RELEASE = f"{base}/latest"
    updater.find_zip_asset = find_zip_asset
    updater._find_signature_asset = lambda assets: ""
    updater.UpdateChecker._do_install = _do_install
