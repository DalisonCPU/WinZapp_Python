"""WinZapp refuses, with an explanation, to start from a network folder.

Reported from a Windows 11 ARM machine in Parallels, whose Downloads folder is
the Mac's (\\\\Mac\\Home\\Downloads): WinZapp extracted there ran npm install
on the share, cmd.exe refused the UNC path as its working directory, and the
user got two pages of npm output and no WinZapp. The database and the Chrome
profile would have lived on the share too, where SQLite's locking is not
reliable. See core/install_location.py.
"""

import pytest

import app_paths
from core import install_location
from core.install_location import DRIVE_REMOTE, is_network_path
from main import MainWindow
from main_window import settings as settings_module


class TestIsNetworkPath:
    @pytest.mark.parametrize("path", [
        r"\\Mac\Home\Downloads\WinZapp (2)\WinZapp",
        r"\\?\UNC\Mac\Home\Downloads\WinZapp",
        "//server/share/WinZapp",
    ])
    def test_unc_paths(self, path):
        assert is_network_path(path, drive_type_of=lambda root: 3) is True

    def test_a_drive_mapped_to_a_share(self):
        seen = []

        def _drive_type(root):
            seen.append(root)
            return DRIVE_REMOTE

        assert is_network_path(r"Y:\WinZapp", drive_type_of=_drive_type) is True
        assert seen == ["Y:\\"]

    @pytest.mark.parametrize("path", [r"C:\Users\nuno\WinZapp", r"\\?\C:\WinZapp"])
    def test_a_local_drive(self, path):
        assert is_network_path(path, drive_type_of=lambda root: 3) is False

    @pytest.mark.parametrize("path", ["", None, "WinZapp\\data"])
    def test_nothing_to_judge(self, path):
        assert is_network_path(path, drive_type_of=lambda root: DRIVE_REMOTE) is False

    def test_a_drive_that_cannot_be_asked_about_is_not_refused(self):
        def _broken(root):
            raise OSError("no such drive")

        assert is_network_path(r"Z:\WinZapp", drive_type_of=_broken) is False


class _I18n:
    def t(self, key):
        return key + " {path}" if key == "network_install_location_message" else key


class _Window:
    _refuse_network_install_location = MainWindow._refuse_network_install_location

    def __init__(self, background_mode=False):
        self.background_mode = background_mode
        self.i18n = _I18n()


@pytest.fixture
def boxes(monkeypatch):
    shown = []
    monkeypatch.setattr(settings_module.wx, "MessageBox",
                        lambda message, title, style: shown.append((message, title)))
    return shown


def _installed_at(monkeypatch, base, network):
    monkeypatch.setattr(app_paths, "global_dir", lambda *parts: base + r"\data\global")
    monkeypatch.setattr(install_location, "is_network_path", lambda path: network)


class TestTheStartupCheck:
    def test_a_network_folder_is_explained_and_the_app_closes(self, monkeypatch, boxes):
        _installed_at(monkeypatch, r"\\Mac\Home\Downloads\WinZapp", network=True)

        with pytest.raises(SystemExit):
            _Window()._refuse_network_install_location()

        assert boxes == [(
            r"network_install_location_message \\Mac\Home\Downloads\WinZapp",
            "network_install_location_title",
        )]

    def test_a_local_folder_starts_normally(self, monkeypatch, boxes):
        _installed_at(monkeypatch, r"C:\WinZapp", network=False)

        _Window()._refuse_network_install_location()

        assert boxes == []

    def test_in_the_background_it_closes_without_a_dialog(self, monkeypatch, boxes):
        """An autostart at logon has nobody to read a dialog; the log says why."""
        _installed_at(monkeypatch, r"\\Mac\Home\Downloads\WinZapp", network=True)

        with pytest.raises(SystemExit):
            _Window(background_mode=True)._refuse_network_install_location()

        assert boxes == []


def test_it_runs_before_anything_is_installed():
    """By source: the check has to come before npm install and before the
    terms dialog, or the user still gets the npm output first."""
    import inspect

    source = inspect.getsource(MainWindow.__init__)
    check = source.index("self._refuse_network_install_location()")
    assert check < source.index("self.ensure_api_modules_installed()")
    assert check < source.index("self._check_terms_acceptance()")
