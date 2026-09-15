"""Tests for .github/scripts/audit_wpp_upgrade.py.

The audit decides whether a WPPConnect Server bump is a one-line pin change or
real porting work, and it is wrong in both directions at a cost: a missed
intersection silently discards upstream work on the next rebuild, while
flagging a dependency that merely flows through sends someone chasing a
non-problem — the exact reasoning error CLAUDE.md warns is the trap here.

Every test drives the pure functions with literal payloads, so nothing reaches
the network. The two real ranges below are the ones CLAUDE.md documents, which
is what makes them worth pinning: 2.10.18 -> 2.10.21 touched two files WinZapp
overrides, and 2.10.21 -> 2.10.24 touched none.
"""

import importlib.util
import os

import pytest

_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".github", "scripts", "audit_wpp_upgrade.py",
)


@pytest.fixture(scope="module")
def audit():
    spec = importlib.util.spec_from_file_location("_wpp_upgrade_audit", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The upstream file list of the real v2.10.18...v2.10.21 compare.
CHANGED_2_10_18_TO_21 = [
    ".dockerignore", ".env.example", ".github/workflows/docker.yml", ".gitignore",
    ".npmignore", "CHANGELOG.md", "README.md", "docker-compose.yml", "package.json",
    "scripts/check-compose-config.cjs", "src/config.test.ts", "src/config.ts",
    "src/index.ts", "yarn.lock",
]

# The real v2.10.21...v2.10.24 compare: four dependency bumps, three releases.
CHANGED_2_10_21_TO_24 = ["CHANGELOG.md", "package.json", "yarn.lock"]


class TestDiscardedUpstreamChanges:
    def test_it_names_the_files_the_restore_overwrites(self, audit):
        assert audit.discarded_upstream_changes(CHANGED_2_10_18_TO_21) == [
            "src/config.ts", "src/index.ts",
        ]

    def test_a_dependency_only_range_discards_nothing(self, audit):
        assert audit.discarded_upstream_changes(CHANGED_2_10_21_TO_24) == []

    def test_a_sibling_test_file_is_not_the_patched_file(self, audit):
        """src/config.test.ts is upstream's own and flows through untouched;
        reading it as src/config.ts would invent porting work every time."""
        assert "src/config.test.ts" not in audit.discarded_upstream_changes(
            CHANGED_2_10_18_TO_21
        )

    def test_it_reads_the_real_lists_rather_than_a_copy(self, audit):
        """The audit must never answer against a stale restatement of the
        very lists it is checking."""
        import setup_api

        assert audit.patched_paths() == (
            set(setup_api.CUSTOM_ROOT_FILES) | set(setup_api.CUSTOM_SRC_FILES)
        )
        assert "src/controller/deviceController.ts" in audit.patched_paths()
        assert "start.js" in audit.patched_paths()


class TestDependencyChanges:
    def test_a_moved_range_is_reported_per_block(self, audit):
        old = {"dependencies": {"multer": "^2.2.0"}, "peerDependencies": {"mongoose": "^8.23.0"}}
        new = {"dependencies": {"multer": "^2.4.0"}, "peerDependencies": {"mongoose": "^8.24.4"}}

        assert audit.dependency_changes(old, new) == {
            ("dependencies", "multer"): ("^2.2.0", "^2.4.0"),
            ("peerDependencies", "mongoose"): ("^8.23.0", "^8.24.4"),
        }

    def test_an_unchanged_dependency_is_absent(self, audit):
        pkg = {"dependencies": {"express": "4.22.2"}}
        assert audit.dependency_changes(pkg, pkg) == {}

    def test_a_dropped_dependency_reports_none_on_the_new_side(self, audit):
        """A key leaving `dependencies` matters as much as a moved range:
        WinZapp's own patches import several of them at runtime."""
        old = {"dependencies": {"qrcode": "^1.5.4"}}
        assert audit.dependency_changes(old, {"dependencies": {}}) == {
            ("dependencies", "qrcode"): ("^1.5.4", None),
        }

    def test_the_version_field_is_not_a_dependency(self, audit):
        """Every one of these bumps moves "version"; reporting it would make
        every audit look like it changed something."""
        old = {"version": "2.10.21", "dependencies": {"express": "4.22.2"}}
        new = {"version": "2.10.24", "dependencies": {"express": "4.22.2"}}
        assert audit.dependency_changes(old, new) == {}


class TestSplitByOverride:
    def test_the_security_bumps_are_the_benign_half(self, audit):
        """multer and sharp are NOT in _PATCHED_DEPENDENCY_KEYS, which is how
        upstream's security bumps arrive without WinZapp doing anything."""
        changes = {
            ("dependencies", "multer"): ("^2.2.0", "^2.4.0"),
            ("dependencies", "sharp"): ("^0.34.5", "^0.35.0"),
        }
        overridden, flowing = audit.split_by_override(changes)

        assert overridden == {}
        assert set(flowing) == set(changes)

    def test_an_overridden_key_is_separated_out(self, audit):
        changes = {
            ("dependencies", "qrcode"): ("^1.5.4", "^1.6.0"),
            ("dependencies", "multer"): ("^2.2.0", "^2.4.0"),
        }
        overridden, flowing = audit.split_by_override(changes)

        assert list(overridden) == [("dependencies", "qrcode")]
        assert list(flowing) == [("dependencies", "multer")]

    def test_nothing_is_lost_or_duplicated(self, audit):
        changes = {
            ("dependencies", "zod"): ("^3.25.0", "^3.26.0"),
            ("devDependencies", "mongoose"): ("^8.23.0", "^8.24.4"),
            ("dependencies", "prom-client"): ("^14.2.0", "^15.0.0"),
        }
        overridden, flowing = audit.split_by_override(changes)

        assert set(overridden) | set(flowing) == set(changes)
        assert not set(overridden) & set(flowing)


class TestHomologatedPair:
    def test_a_moved_pin_is_flagged(self, audit):
        changes = {("dependencies", "@wppconnect-team/wppconnect"): ("^2.3.3", "^2.4.0")}
        assert audit.homologated_pair_moved(changes) == changes

    def test_wa_js_counts_too(self, audit):
        changes = {("dependencies", "@wppconnect/wa-js"): ("^4.6.0", "^4.7.0")}
        assert audit.homologated_pair_moved(changes) == changes

    def test_wa_version_is_deliberately_not_part_of_the_pair(self, audit):
        """@wppconnect/wa-version is the expiring WhatsApp HTML catalogue, not
        an API surface — it stays updateable and must not raise a flag."""
        changes = {("dependencies", "@wppconnect/wa-version"): ("^1.5.4490", "^1.5.4834")}
        assert audit.homologated_pair_moved(changes) == {}

    def test_the_real_bump_moved_neither(self, audit):
        changes = {
            ("dependencies", "express-rate-limit"): ("^8.2.0", "^8.7.0"),
            ("dependencies", "multer"): ("^2.2.0", "^2.4.0"),
        }
        assert audit.homologated_pair_moved(changes) == {}
