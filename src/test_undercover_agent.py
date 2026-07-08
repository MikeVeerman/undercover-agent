#!/usr/bin/env python3
"""Tests for the undercover-agent CLI (the sibling `undercover-agent.py`).

Stdlib-only (unittest) so it runs with zero dependencies:

    python3 -m unittest test_undercover_agent      # from this directory
    pytest test_undercover_agent.py                # also works (pytest runs unittest)

The module under test has a hyphen in its filename, so it is loaded by path via
SourceFileLoader rather than a plain import.
"""

import contextlib
import importlib.machinery
import importlib.util
import json
import os
import re
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_HERE, "undercover-agent.py")
_loader = importlib.machinery.SourceFileLoader("undercover_agent_under_test", _SRC)
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
ua = importlib.util.module_from_spec(_spec)
_loader.exec_module(ua)


@contextlib.contextmanager
def _in_tmp_repo(input_lines=None):
    """chdir into a throwaway dir with an optional .undercover-agent/input.txt."""
    prev = os.getcwd()
    d = tempfile.mkdtemp()
    try:
        os.chdir(d)
        if input_lines is not None:
            os.makedirs(ua.CONFIG_DIR, exist_ok=True)
            with open(ua.INPUT_PATH, "w") as f:
                f.write("".join(f"{ln}\n" for ln in input_lines))
        yield d
    finally:
        os.chdir(prev)


def _slurp(path):
    with open(path) as f:
        return f.read()


def _read(rel):
    p = os.path.join(ua.CONFIG_DIR, rel)
    return _slurp(p) if os.path.exists(p) else None


# --- Fakes for exercising processFile without spawning a real `claude`. -------

class _FakeStdin:
    def write(self, _s):  # noqa: D401
        pass

    def close(self):
        pass


class _FakeStderr:
    def __init__(self, text=""):
        self._text = text

    def read(self):
        return self._text


class _FakeProc:
    """A subprocess.Popen stand-in whose process has already exited."""

    def __init__(self, returncode, stderr=""):
        self.returncode = returncode
        self.stdin = _FakeStdin()
        self.stdout = iter([])          # nothing to stream
        self.stderr = _FakeStderr(stderr)

    def poll(self):
        return self.returncode          # already done → the read loop is skipped

    def wait(self, timeout=None):
        return self.returncode

    def terminate(self):
        pass

    def kill(self):
        pass


BASE_CFG = {
    "framework": "TS (Vitest)",
    "test_file": "{dir}/{name}.test.{ext}",
    "test_command": "pnpm vitest run $TESTFILE --coverage.include=$FILENAME",
    "coverage_report": "coverage/clover.xml",
    "desired_coverage": 100,
    "prefer": "",
    "rules": [],
}


class DeriveTestFile(unittest.TestCase):
    def test_templates(self):
        cases = [
            ("{dir}/{name}.test.{ext}", "src/foo.ts", "src/foo.test.ts"),
            ("{dir}/{name}.test.{ext}", "foo.ts", "foo.test.ts"),        # repo-root: no leading slash
            ("{dir}/{name}Test.{ext}", "app/Http/Bar.php", "app/Http/BarTest.php"),
            ("{dir}/test_{name}.{ext}", "pkg/mod.py", "pkg/test_mod.py"),
        ]
        for tpl, fp, want in cases:
            with self.subTest(fp=fp):
                self.assertEqual(ua.deriveTestFile(fp, tpl), want)


class BuildPrompt(unittest.TestCase):
    def test_no_leftover_placeholders_and_command(self):
        cfg = dict(ua.PRESETS["vitest"])
        p = ua.buildPrompt("src/foo.ts", cfg)
        self.assertEqual(re.findall(r"\$[A-Z_]+", p), [], "unresolved placeholders remain")
        self.assertIn("pnpm vitest run src/foo.test.ts", p)
        self.assertIn("--coverage.include=src/foo.ts", p)
        self.assertIn("We are testing a TypeScript (Vitest) project.", p)

    def test_pest_filter_uses_testname(self):
        p = ua.buildPrompt("app/Bar.php", dict(ua.PRESETS["pest"]))
        self.assertIn("--filter=BarTest", p)
        self.assertEqual(re.findall(r"\$[A-Z_]+", p), [])


class LoadConfig(unittest.TestCase):
    def test_defaults_applied(self):
        with _in_tmp_repo():
            os.makedirs(ua.CONFIG_DIR, exist_ok=True)
            with open(ua.CONFIG_PATH, "w") as f:
                json.dump(BASE_CFG, f)
            cfg = ua.loadConfig()
            self.assertEqual(cfg["timeout_seconds"], 1800)   # defaulted
            self.assertEqual(cfg["desired_coverage"], 100)
            self.assertNotIn("model", cfg)                   # optional, not forced

    def test_missing_required_key_exits(self):
        with _in_tmp_repo():
            os.makedirs(ua.CONFIG_DIR, exist_ok=True)
            broken = {k: v for k, v in BASE_CFG.items() if k != "test_command"}
            with open(ua.CONFIG_PATH, "w") as f:
                json.dump(broken, f)
            with self.assertRaises(SystemExit):
                ua.loadConfig()

    def test_missing_config_exits(self):
        with _in_tmp_repo():
            with self.assertRaises(SystemExit):
                ua.loadConfig()


class Scaffold(unittest.TestCase):
    def test_writes_config_and_input(self):
        with _in_tmp_repo():
            ua.scaffold("vitest")
            with open(ua.CONFIG_PATH) as f:
                cfg = json.load(f)
            self.assertEqual(cfg["model"], "claude-sonnet-5")
            self.assertTrue(os.path.exists(ua.INPUT_PATH))

    def test_refuses_overwrite(self):
        with _in_tmp_repo():
            ua.scaffold("vitest")
            with open(ua.CONFIG_PATH) as f:
                json.load(f)                         # valid JSON
            with open(ua.CONFIG_PATH, "a") as f:
                f.write("SENTINEL")                  # corrupt it
            ua.scaffold("vitest")                    # must NOT overwrite
            self.assertIn("SENTINEL", _slurp(ua.CONFIG_PATH))

    def test_unknown_preset_exits(self):
        with _in_tmp_repo():
            with self.assertRaises(SystemExit):
                ua.scaffold("nope")


class ClaudeArgs(unittest.TestCase):
    """The claude invocation includes --model iff cfg has one; always -p + Bash(*)."""

    def _argv_for(self, cfg):
        captured = {}

        def recorder(args, **_kw):
            captured["argv"] = args
            return _FakeProc(0)                        # behave as a clean success

        orig = ua.subprocess.Popen
        ua.subprocess.Popen = recorder
        try:
            with _in_tmp_repo(input_lines=["src/foo.ts"]):
                ua.processFile("src/foo.ts", cfg)
        finally:
            ua.subprocess.Popen = orig
        return captured.get("argv", [])

    def test_model_present(self):
        argv = self._argv_for(dict(BASE_CFG, model="claude-sonnet-5"))
        self.assertIn("--model", argv)
        self.assertEqual(argv[argv.index("--model") + 1], "claude-sonnet-5")
        self.assertIn("-p", argv)
        self.assertIn("Bash(*)", argv)

    def test_model_absent(self):
        argv = self._argv_for(dict(BASE_CFG))
        self.assertNotIn("--model", argv)
        self.assertIn("-p", argv)


class FailureTracking(unittest.TestCase):
    """Regression for the silent-drain bug: outcome is classified before input.txt
    is touched; failures land in failed.txt and stay in input.txt for re-run."""

    def _run(self, popen_impl, target="src/foo.ts", others=()):
        orig = ua.subprocess.Popen
        ua.subprocess.Popen = popen_impl
        try:
            with _in_tmp_repo(input_lines=[target, *others]):
                ua.processFile(target, dict(BASE_CFG))
                return {
                    "input": _slurp(ua.INPUT_PATH),
                    "failed": _read("failed.txt"),
                    "processed": _read("processed.txt"),
                    "timedout": _read("timedout.txt"),
                }
        finally:
            ua.subprocess.Popen = orig

    def test_success_removes_and_records_processed(self):
        r = self._run(lambda *a, **k: _FakeProc(0))
        self.assertNotIn("src/foo.ts", r["input"])          # removed from queue
        self.assertIn("src/foo.ts", r["processed"])
        self.assertIsNone(r["failed"])

    def test_run_failure_keeps_in_input_and_records_failed(self):
        r = self._run(lambda *a, **k: _FakeProc(1, stderr="boom: coverage tool missing"))
        self.assertIn("src/foo.ts", r["input"])             # KEPT for re-run
        self.assertIsNotNone(r["failed"])
        self.assertIn("src/foo.ts", r["failed"])
        self.assertIn("boom: coverage tool missing", r["failed"])  # reason captured
        self.assertIsNone(r["processed"])

    def test_spawn_failure_no_nameerror_and_records_failed(self):
        def boom(*_a, **_k):
            raise OSError("no claude on PATH")
        r = self._run(boom)                                 # must NOT raise NameError
        self.assertIn("src/foo.ts", r["input"])             # KEPT for re-run
        self.assertIsNotNone(r["failed"])
        self.assertIn("no claude on PATH", r["failed"])     # spawn reason captured

    def test_only_target_line_affected(self):
        r = self._run(lambda *a, **k: _FakeProc(0), others=["src/bar.ts"])
        self.assertNotIn("src/foo.ts", r["input"])
        self.assertIn("src/bar.ts", r["input"])             # sibling untouched


if __name__ == "__main__":
    unittest.main(verbosity=2)
