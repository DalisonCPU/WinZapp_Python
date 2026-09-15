"""Answer, for a proposed WPPConnect Server bump, the three questions that decide it.

Bumping `client/wpp_minimum_version.txt` is a real change, not a floor:
`setup_api.py` checks that exact tag out, so every fresh install and every
in-app "reinstall API" gets it. The check that matters is not the release
notes — those are usually empty for these bumps — but the upstream diff read
against what WinZapp overrides:

1. **Source files upstream changed that WinZapp's restore discards.** Anything
   in `CUSTOM_ROOT_FILES + CUSTOM_SRC_FILES` that also moved upstream is work
   thrown away silently, because `setup_api.py` copies `client/api_patches/`
   over the checkout. Anything outside that intersection flows through
   untouched and needs no thought at all.
2. **Dependencies WinZapp overrides.** `_PATCHED_DEPENDENCY_KEYS` is
   deliberately narrow so upstream's own ranges govern everything else — which
   is how upstream's security bumps arrive without us doing anything. So the
   reasoning here is the *opposite* of (1), and getting it backwards is the
   trap: a changed dependency we do NOT override is good news, and upstream
   moving a caret we DO override is not by itself a reason to move our pin.
3. **Whether the homologated pair moved.** `@wppconnect-team/wppconnect` and
   `@wppconnect/wa-js` are pinned exact against the four `node_modules` patch
   modules. Upstream moving its own declaration does not move ours, but it is
   the one dependency change worth a human's eyes.

The lists are imported from `setup_api.py` rather than restated here, so this
audit cannot answer against a stale copy of the very thing it is checking.

Reads GitHub through `gh`, which every maintainer running this already has.
Exit 1 means "a human has to look", never "the bump is wrong".

Usage:
    python .github/scripts/audit_wpp_upgrade.py 2.10.21 2.10.24
    python .github/scripts/audit_wpp_upgrade.py 2.10.24   # from the committed pin

tests/test_wpp_upgrade_audit.py covers the pure functions.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

ROOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, ROOT_DIR)

from setup_api import (  # noqa: E402
    CUSTOM_ROOT_FILES,
    CUSTOM_SRC_FILES,
    _PATCHED_DEPENDENCY_KEYS,
)

UPSTREAM_REPO = "wppconnect-team/wppconnect-server"

# The two keys that are one homologated pair, not two independent pins — see
# the send-compatibility contract in CLAUDE.md.
HOMOLOGATED_PAIR = ("@wppconnect-team/wppconnect", "@wppconnect/wa-js")

_DEPENDENCY_BLOCKS = ("dependencies", "devDependencies", "peerDependencies")


def patched_paths() -> set:
    """Every upstream path WinZapp restores its own copy of after a checkout."""
    return set(CUSTOM_ROOT_FILES) | set(CUSTOM_SRC_FILES)


def discarded_upstream_changes(changed_paths) -> list:
    """Upstream changes that WinZapp's restore silently overwrites.

    This is the whole source-side audit: a non-empty result is upstream work
    that will not reach the built server until it is ported into
    client/api_patches/ by hand.
    """
    return sorted(set(changed_paths) & patched_paths())


def dependency_changes(old_pkg: dict, new_pkg: dict) -> dict:
    """{name: (old_range, new_range)} for every dependency that moved.

    Covers all three blocks, and reports a dependency that appeared or was
    dropped as None on the missing side — a key leaving `dependencies` matters
    as much as one changing range, since WinZapp imports several of them at
    runtime through its own patches.
    """
    def flatten(pkg):
        out = {}
        for block in _DEPENDENCY_BLOCKS:
            for name, spec in (pkg.get(block) or {}).items():
                out[(block, name)] = spec
        return out

    old, new = flatten(old_pkg), flatten(new_pkg)
    changes = {}
    for key in sorted(set(old) | set(new)):
        if old.get(key) != new.get(key):
            changes[key] = (old.get(key), new.get(key))
    return changes


def split_by_override(changes: dict) -> tuple:
    """Partition *changes* into the ones WinZapp overrides and the rest.

    Returns (overridden, flowing). "flowing" is the benign half: upstream's own
    range governs it, so the bump carries it for free. "overridden" is where
    api_patches/package.json's value wins regardless, so upstream moving is
    informational — it never changes what gets installed on its own.
    """
    overridden, flowing = {}, {}
    for key, value in changes.items():
        target = overridden if key[1] in _PATCHED_DEPENDENCY_KEYS else flowing
        target[key] = value
    return overridden, flowing


def homologated_pair_moved(changes: dict) -> dict:
    """The subset of *changes* touching the exact-pinned runtime pair."""
    return {k: v for k, v in changes.items() if k[1] in HOMOLOGATED_PAIR}


def _gh_json(path: str):
    out = subprocess.run(
        ["gh", "api", path], capture_output=True, text=True, check=True
    ).stdout
    return json.loads(out)


def fetch_changed_paths(old_tag: str, new_tag: str) -> list:
    payload = _gh_json(f"repos/{UPSTREAM_REPO}/compare/v{old_tag}...v{new_tag}")
    return [f["filename"] for f in payload.get("files", [])]


def fetch_package_json(tag: str) -> dict:
    import base64

    payload = _gh_json(f"repos/{UPSTREAM_REPO}/contents/package.json?ref=v{tag}")
    return json.loads(base64.b64decode(payload["content"]).decode("utf-8"))


def committed_pin() -> str:
    path = os.path.join(ROOT_DIR, "client", "wpp_minimum_version.txt")
    with open(path, encoding="utf-8") as fh:
        return fh.read().strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old_tag", nargs="?", help="current tag (default: the committed pin)")
    parser.add_argument("new_tag", help="candidate tag")
    args = parser.parse_args()

    old_tag = args.old_tag or committed_pin()
    new_tag = args.new_tag
    if args.old_tag is None:
        print(f"[INFO] Comparing against the committed pin {old_tag}.")
    print(f"=== WPPConnect Server {old_tag} -> {new_tag} ===\n")

    changed = fetch_changed_paths(old_tag, new_tag)
    discarded = discarded_upstream_changes(changed)
    source_changes = [p for p in changed if p not in ("CHANGELOG.md", "package.json", "yarn.lock")]

    print(f"Files changed upstream: {len(changed)}")
    if not source_changes:
        print("  No source changes at all — dependency/release commits only.")
    for path in sorted(source_changes):
        print(f"  {'DISCARDED BY RESTORE' if path in discarded else 'flows through '} {path}")
    print()

    changes = dependency_changes(
        fetch_package_json(old_tag), fetch_package_json(new_tag)
    )
    # "version" lives outside the dependency blocks, so it never reaches here.
    overridden, flowing = split_by_override(changes)
    pair = homologated_pair_moved(changes)

    print(f"Dependencies changed: {len(changes)}")
    for (block, name), (was, now) in sorted(flowing.items()):
        print(f"  flows through  {name} ({block}): {was} -> {now}")
    for (block, name), (was, now) in sorted(overridden.items()):
        print(f"  WINZAPP OVERRIDES {name} ({block}): {was} -> {now}")
    print()

    problems = []
    if discarded:
        problems.append(
            f"{len(discarded)} upstream change(s) land in files WinZapp restores over: "
            f"{', '.join(discarded)}. Port them into client/api_patches/ or accept "
            f"losing them, deliberately."
        )
    if pair:
        problems.append(
            "The homologated runtime pair moved upstream: "
            + ", ".join(f"{name} {was} -> {now}" for (_b, name), (was, now) in sorted(pair.items()))
            + ". WinZapp's exact pin still wins, so nothing changes by itself — but "
            "re-homologating means running all four node_modules patches against the "
            "candidate first (see the wppconnect-patch skill)."
        )

    if problems:
        print("NEEDS A HUMAN:")
        for line in problems:
            print(f"  - {line}")
        return 1

    print("Clean: nothing upstream changed that WinZapp overrides, and the "
          "homologated pair is untouched. Bump client/wpp_minimum_version.txt "
          "and let setup_api.py rebuild.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
