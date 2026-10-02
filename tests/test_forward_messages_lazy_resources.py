"""Forwarding must survive a WhatsApp Web build whose forward module cannot be required.

Measured 2026-10-02 on WhatsApp Web 2.3000.1049007170: every POST
/forward-messages answered 500 ``forward_messages_not_available``. wa-js's
``WPP.chat.forwardMessages`` awaits ``ensureLazyModule('WAWebChatForwardMessage')``
and then needs its own ``functions.forwardMessages`` binding; ``require()`` of
that module throws "unresolved dependencies" because a script the Bootloader
lists among the page's resources was never loaded, and wa-js neither loads it
nor binds late. client/api_patches/src/util/forwardRuntime.ts loads the
unloaded resources and calls WhatsApp's function directly.

The code under test is a string evaluated in a real page, so two kinds of check:
source contracts (like tests/test_status_reply_quotes_the_live_model.py) and,
when ``node`` is on PATH, the very same text run against a fake ``window``.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "client" / "api_patches" / "src"
RUNTIME = SRC / "util" / "forwardRuntime.ts"
CONTROLLER = SRC / "controller" / "deviceController.ts"


@pytest.fixture(scope="module")
def runtime_ts() -> str:
    return RUNTIME.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def page_source(runtime_ts: str) -> str:
    match = re.search(r"String\.raw`(.*?)`;", runtime_ts, re.S)
    assert match, "the in-page function must stay a String.raw template"
    return match.group(1)


@pytest.fixture(scope="module")
def handler() -> str:
    source = CONTROLLER.read_text(encoding="utf-8")
    start = source.index("export async function forwardMessages")
    return source[start:source.index("export async function", start + 10)]


class TestWiring:
    def test_the_handler_uses_the_runtime_not_the_library(self, handler):
        assert "buildForwardRuntimeExpression(" in handler
        assert "forwardMessagesV2" not in handler, (
            "the library call is the one that fails with "
            "forward_messages_not_available"
        )

    def test_the_handler_does_not_retry_or_fall_back(self, handler):
        assert handler.count("page.evaluate(") == 1, (
            "a second evaluate after a failure could forward twice"
        )

    def test_a_failure_is_reported_with_its_detail(self, handler):
        assert "status(500)" in handler
        assert "detail:" in handler

    def test_the_success_shape_is_unchanged(self, handler):
        assert "res.status(201).json({ status: 'success', response: response })" \
            in handler

    def test_the_file_is_in_every_list(self):
        name = "src/util/forwardRuntime.ts"
        for path in ("setup_api.py", "build.py", "client/ui/dialogs/api_setup.py",
                     "tests/test_api_patches_in_sync.py"):
            assert name in (ROOT / path).read_text(encoding="utf-8"), path


class TestPageFunctionContract:
    def test_only_whatsapp_static_scripts_are_loaded(self, page_source):
        assert "url.protocol === 'https:'" in page_source
        assert "url.hostname === 'static.whatsapp.net'" in page_source
        assert "url.pathname.endsWith('.js')" in page_source

    def test_the_direct_call_arguments(self, page_source):
        call = page_source[page_source.index("mod.forwardMessages({"):]
        call = call[:call.index("});")]
        for part in ("chat: chat", "msgs: msgs", "multicast: false",
                     "includeCaption: false", "appendedText: false"):
            assert part in call

    def test_there_is_exactly_one_direct_call(self, page_source):
        assert page_source.count("mod.forwardMessages(") == 1

    def test_the_send_is_not_wrapped_in_a_catch(self, page_source):
        send = page_source.index("mod.forwardMessages(")
        assert "catch" not in page_source[send:], (
            "a rejected forward must propagate, never be retried"
        )

    def test_it_is_self_contained(self, page_source):
        assert "`" not in page_source and "${" not in page_source


HARNESS = r"""
const fs = require('fs');
const [, , tsPath, scenario] = process.argv;
const ts = fs.readFileSync(tsPath, 'utf8');
const src = /String\.raw`([\s\S]*?)`;/.exec(ts)[1];
const calls = { forward: [], lib: [], scripts: [] };
const world = JSON.parse(process.env.WORLD);
let loadedScripts = 0;
const modAvailable = () => loadedScripts >= world.scriptsNeeded;
const mod = {
  forwardMessages: async (a) => {
    calls.forward.push(a);
    if (world.rejectForward) throw new Error('rejected by whatsapp');
    return ['sent'];
  },
};
const resources = new Map(Object.entries(world.resources));
const componentMap = new Map(Object.entries(world.components));
global.window = {
  require: (name) => {
    if (name === 'Bootloader') return { __debug: { componentMap, resources, loaded: new Set() } };
    if (name === 'WAWebChatForwardMessage') {
      if (modAvailable() || world.alwaysWorks) return mod;
      const e = new Error('x');
      e.messageParams = ['m', 'Requiring module WAWebChatForwardMessage with unresolved dependencies: WAWebDualUploadsSendPolicy is not defined'];
      throw e;
    }
    throw new Error('unknown module ' + name);
  },
  WPP: {
    whatsapp: { functions: world.bound ? { forwardMessages: () => 1 } : {} },
    chat: {
      find: async (id) => ({ chatId: id }),
      getMessageById: async (id) => ({ msgId: id }),
      forwardMessages: async (c, ids) => { calls.lib.push([c, ids]); return ['lib']; },
    },
  },
};
global.document = {
  head: {
    appendChild: (s) => {
      calls.scripts.push(s.src);
      setTimeout(() => {
        if (world.scriptFails) return s.onerror();
        loadedScripts += 1;
        s.onload();
      }, 0);
    },
  },
  createElement: () => ({}),
};
const fn = eval('(' + src + ')');
const args = { chatId: 'chat@c.us', messageIds: ['a', 'b'] };
(async () => {
  let out, err = null;
  try {
    const runs = await Promise.all(world.concurrent ? [fn(args), fn(args)] : [fn(args)]);
    out = runs;
  } catch (e) { err = String(e && e.message || e); }
  console.log(JSON.stringify({ out, err, calls }));
})();
"""

COMPONENTS = {
    "WAWebForwardMessageFlow.react": {"r": ["h1", "h2", "h3", "h4"]},
    "WAWebOther": {"r": ["h9"]},
}
RESOURCES = {
    "h1": {"src": "https://static.whatsapp.net/rsrc.php/v4/y4/l/en_US/a.js"},
    "h2": {"src": "https://static.whatsapp.net/rsrc.php/v4/y4/l/b.css"},
    "h3": {"src": "https://evil.example/c.js"},
    "h4": {"src": "http://static.whatsapp.net/d.js"},
    "h9": {"src": "https://static.whatsapp.net/never-asked.js"},
}


def _run(tmp_path, **world):
    base = {"scriptsNeeded": 1, "resources": RESOURCES, "components": COMPONENTS}
    base.update(world)
    script = tmp_path / "harness.js"
    script.write_text(HARNESS, encoding="utf-8")
    import os
    env = dict(os.environ, WORLD=json.dumps(base))
    done = subprocess.run(
        ["node", str(script), str(RUNTIME), "x"],
        capture_output=True, text=True, timeout=20, env=env,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node missing")


@needs_node
class TestRunInFakePage:
    def test_heals_with_whitelisted_scripts_and_calls_once(self, tmp_path):
        r = _run(tmp_path)
        assert r["err"] is None
        assert r["calls"]["scripts"] == [RESOURCES["h1"]["src"]]
        assert len(r["calls"]["forward"]) == 1
        args = r["calls"]["forward"][0]
        assert args == {
            "chat": {"chatId": "chat@c.us"},
            "msgs": [{"msgId": "a"}, {"msgId": "b"}],
            "multicast": False, "includeCaption": False, "appendedText": False,
        }
        assert r["out"] == [{"ok": True, "response": ["sent"]}]

    def test_unhealable_reports_the_chain_and_sends_nothing(self, tmp_path):
        r = _run(tmp_path, scriptFails=True)
        assert r["calls"]["forward"] == []
        out = r["out"][0]
        assert out["ok"] is False
        assert "WAWebDualUploadsSendPolicy is not defined" in out["detail"]

    def test_a_rejected_forward_is_not_retried(self, tmp_path):
        r = _run(tmp_path, rejectForward=True)
        assert r["err"] == "rejected by whatsapp"
        assert len(r["calls"]["forward"]) == 1

    def test_concurrent_forwards_share_one_heal(self, tmp_path):
        r = _run(tmp_path, concurrent=True)
        assert len(r["calls"]["scripts"]) == 1
        assert len(r["calls"]["forward"]) == 2  # one send per request

    def test_a_working_build_uses_the_library_path(self, tmp_path):
        r = _run(tmp_path, alwaysWorks=True, bound=True)
        assert r["calls"]["forward"] == [] and r["calls"]["scripts"] == []
        assert r["calls"]["lib"] == [["chat@c.us", ["a", "b"]]]
