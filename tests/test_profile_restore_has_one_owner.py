"""A profile restore must be the only thing driving the session while it runs.

Found reviewing issue #203's fix. `_recovery_restart_active` has two owners:
_recover_suspect_profile()'s restore, and _force_whatsapp_session_restart(),
the power-resume zombie restart. The sequence that breaks:

1. The PC resumes and the startup grace reopens.
2. The power restart starts the session and polls it every 2 s.
3. The restarted profile is refused, and its first code starts a restore
   early — which is the new, intended behaviour for a code inside the grace.
4. The power restart then either reads QRCODE and returns, clearing the
   shared flag in its `finally`, or reads the CLOSED the restore produced
   and runs another close/start attempt.

Either way something starts Chrome over a profile being copied back: the
health poll's /start-session once the flag is gone, or the restart's own next
attempt. What that does depends on where the copy is. The restore may
kill the new browser, or the session may come up on an empty profile, with
the good snapshot spent and the original moved to `.broken`.

So the restore gets a flag only it clears (`_profile_restore_in_flight`),
every path that can start a session reads it, and no early restore starts
while another restart owns the session.
"""

import inspect
import time

from core.websocket_client import WebSocketClient
from main import MainWindow


class TestNothingStartsASessionUnderARestore:
    def test_the_auto_start_block_reads_the_restore_flag(self):
        src = inspect.getsource(MainWindow.check_wa_connection_http)
        call = src[src.index("cs.auto_start_block_reason("):]
        call = call[:call.index("if block:")]
        assert "_profile_restore_in_flight" in call, (
            "the CLOSED auto-start guard only reads _recovery_restart_active, "
            "which the power-resume restart can clear mid-restore")

    def test_a_restore_in_flight_is_a_self_inflicted_teardown(self):
        class _Stub:
            _self_inflicted_teardown_expected = MainWindow._self_inflicted_teardown_expected
            _shutting_down = False
            _wpp_updating = False
            _recovery_restart_active = False     # cleared by the other owner
            _restarting_wpp_session = False
            _profile_restore_in_flight = True

        assert _Stub()._self_inflicted_teardown_expected() is True

    def test_the_power_resume_restart_stops_before_restarting_under_a_restore(self):
        attempts = []

        class _Stub:
            _run_recovery_attempts = MainWindow._run_recovery_attempts
            _RECOVERY_MAX_ATTEMPTS = MainWindow._RECOVERY_MAX_ATTEMPTS
            _profile_restore_in_flight = True
            _wa_connected = False

            def _restart_session_once(self, token, attempt=1):
                attempts.append(attempt)

        import connection_state as cs

        _Stub()._run_recovery_attempts("tok", cs)

        assert attempts == [], (
            "the power-resume restart ran a close/start cycle while a profile "
            "restore owned the session")


class _WorthTryingStub:
    token = "sess123:tok"
    global_dir = "/g"

    def _profile_recovery_generation(self):
        return 0

    _profile_restore_worth_trying = MainWindow._profile_restore_worth_trying


class TestNoEarlyRestoreWhileAnotherRestartOwnsTheSession:
    def _stub(self, monkeypatch):
        monkeypatch.setattr("main.pick_restore_generation",
                            lambda *a, **kw: (False, "ok", False))
        return _WorthTryingStub()

    def test_not_during_the_power_resume_restart(self, monkeypatch):
        stub = self._stub(monkeypatch)
        stub._recovery_restart_active = True
        assert stub._profile_restore_worth_trying() is False

    def test_not_during_the_in_place_restart(self, monkeypatch):
        stub = self._stub(monkeypatch)
        stub._restarting_wpp_session = True
        assert stub._profile_restore_worth_trying() is False

    def test_once_that_restart_lets_go_the_next_code_may_restore(self, monkeypatch):
        """The power restart stops on its own at the QRCODE the refused profile
        reports, so waiting costs at most one code."""
        stub = self._stub(monkeypatch)
        stub._recovery_restart_active = False
        stub._restarting_wpp_session = False
        assert stub._profile_restore_worth_trying() is True


class TestAStuckRestoreCannotSilenceTheFloodForever:
    """Codes are left to a restore in flight — but only for
    _RESTORE_FLIGHT_IGNORE_SECONDS. A restore still producing codes past that
    has failed to stop the browser, and on `main` before this change those
    codes were at least counted towards the halt."""

    def _handler(self, started_at):
        halts = []

        class _MW:
            settings = {"privateinfo": {"paired": True}}
            _unattended_qr_events = 0
            _qr_flood_halted = False
            _auto_repair_dialog_shown = True      # already offered: halt only
            _pairing_in_progress = False
            _profile_restore_in_flight = True
            _profile_restore_started_at = started_at
            _wa_connect_announced = True
            _wa_startup_time = 0
            _WA_STARTUP_GRACE_SECONDS = 45

            def _is_pairing_dialog_active(self):
                return False

            def _profile_restore_worth_trying(self):
                return False

            def _halt_unattended_qr_session(self):
                halts.append(1)
                self._qr_flood_halted = True

        class _Stub:
            _handle_unattended_qr = WebSocketClient._handle_unattended_qr
            _pairing_attended = WebSocketClient._pairing_attended
            _qr_within_startup_grace = WebSocketClient._qr_within_startup_grace
            _UNATTENDED_QR_LIMIT = WebSocketClient._UNATTENDED_QR_LIMIT
            _REPAIR_DIALOG_CONFIRM_EVENTS = WebSocketClient._REPAIR_DIALOG_CONFIRM_EVENTS
            _RESTORE_FLIGHT_IGNORE_SECONDS = WebSocketClient._RESTORE_FLIGHT_IGNORE_SECONDS

            def __init__(self):
                self.main_window = _MW()

        return _Stub(), halts

    def test_a_recent_restore_still_owns_its_codes(self):
        s, halts = self._handler(time.monotonic())
        for _ in range(WebSocketClient._UNATTENDED_QR_LIMIT * 2):
            s._handle_unattended_qr()
        assert halts == []
        assert s.main_window._unattended_qr_events == 0

    def test_an_overdue_restore_gives_the_flood_its_ceiling_back(self):
        s, halts = self._handler(
            time.monotonic() - WebSocketClient._RESTORE_FLIGHT_IGNORE_SECONDS - 1)
        for _ in range(WebSocketClient._UNATTENDED_QR_LIMIT):
            s._handle_unattended_qr()
        assert halts == [1]

    def test_the_window_covers_the_restores_own_worst_case(self):
        """close-session (10 s) + a release deadline whose polls can run past
        it (20 s + up to 15 s) + the kill (up to 15 s) + its settle (5 s):
        about a minute. The window must clear that with room to spare, or a
        healthy slow restore would have its stragglers counted."""
        assert WebSocketClient._RESTORE_FLIGHT_IGNORE_SECONDS >= 2 * (10 + 20 + 15 + 15 + 5)
