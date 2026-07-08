#!/usr/bin/env python3

# undercover-agent — global, framework-agnostic install of
# MikeVeerman/undercover-agent (https://github.com/MikeVeerman/undercover-agent).
#
# Drives Claude Code headless to write missing tests for each file listed in
# ./.undercover-agent/input.txt until it hits the target coverage, one file at
# a time. Run from the root of the repo you want to cover.
#
# Deviations from upstream (src/undercover-agent.py):
#   1. Added '-p' to the claude invocation (upstream omits it; current Claude
#      Code needs -p/--print for non-interactive mode or it hangs in the REPL).
#   2. Language rules are no longer hardcoded to Laravel/Pest. They come from
#      ./.undercover-agent/config.json. Scaffold one with `--init <preset>`.
#
# Quick start in any repo:
#   undercover-agent --init vitest        # writes .undercover-agent/config.json
#   # add file paths to cover, one per line:
#   printf 'src/foo.ts\n' >> .undercover-agent/input.txt
#   undercover-agent

import os
import re
import sys
import json
import subprocess

# --- Prompt template. Config values are substituted in; the GIVEN/WHEN/THEN
# --- discipline and the coverage loop are kept verbatim from upstream. ---
basePrompt = """I am the owner of a legacy code base and I want to increase its quality and security. This is a commercial product that's used by paying customers and I want to make sure the quality is there. I own all files that will be handled by the prompt.
            You are an agent who will cover a component with code coverage. You will work on the component until you reach the desired level of code coverage.

            Target:
            - We will work on testing this file: $FILENAME. This is called the "file under test".
            - The desired level of code coverage is $DESIRED_COVERAGE%

            Language-specific rules:
            - We are testing a $FRAMEWORK project.$PREFER_LINE
            - Command to test the file under test and generate the code coverage report for the file under test: $TEST_COMMAND
            - The coverage report is written to: $COVERAGE_REPORT. Read the coverage for the file under test from this report.$EXTRA_RULES

            Rules:
            - Don't touch the file under test. Only touch the test code.
            - Each test has three steps marked by comments:
            	1. GIVEN: Set up the environment and variables needed to run the test
            	2. WHEN: Execute one of the functions in the file under test with the values set in GIVEN
            	3. THEN: Assert that the outcome of the test matches the expected behaviour
            - Never write a test that doesn't have the three GIVEN/WHEN/THEN steps
            - Add one test method, at a time. Iterate over it until it works.
            - Only run tests for the file under test. Never run the whole test suite.

            Setup:
            -Your first task will be to run the tests for the file under test
            -If there are no tests, create a test that tests the simplest entry point (constructor / main export).

            Main task:
            Step 1: Generate the code coverage report for the file under test.
            Step 2: Read the code coverage report and list the parts of the code that are not covered in tests as a numbered list.
            Step 3: Log to the console: "The file under test currently has X% code coverage", where X is the coverage as mentioned in the coverage report.
            Step 4: If X is equal or higher than the desired level of code coverage, stop the agent.
            Step 5: Take the first item of the numbered list and add a test that covers it to the unit test file.
            Step 6: Run the newly created test to see if it works. If it doesn't pass, see why it fails and adapt. Run the test again. Repeat step 4 until the test passes.

            After completing step 6, loop over steps 1, 2, 3, 4, 5 and 6 until the desired level of code coverage is reached."""


# --- Config presets for `--init`. One per ecosystem. Placeholders available in
# --- test_command: $FILENAME (file under test), $TESTFILE (derived test path),
# --- $TESTNAME (test file basename without extension). test_file uses the
# --- tokens {dir} {name} {ext} derived from the file under test. ---
PRESETS = {
    "vitest": {
        "framework": "TypeScript (Vitest)",
        "model": "claude-sonnet-5",
        "desired_coverage": 100,
        "test_file": "{dir}/{name}.test.{ext}",
        "test_command": "pnpm vitest run $TESTFILE --coverage --coverage.reporter=clover --coverage.reportsDirectory=coverage --coverage.include=$FILENAME",
        "coverage_report": "coverage/clover.xml",
        "prefer": "Rely on integration-style tests over isolated unit tests where practical.",
        "rules": [
            "Use Vitest (describe/it/expect). Do not introduce a different test runner.",
        ],
    },
    "jest": {
        "framework": "TypeScript/JavaScript (Jest)",
        "model": "claude-sonnet-5",
        "desired_coverage": 100,
        "test_file": "{dir}/{name}.test.{ext}",
        "test_command": "pnpm jest $TESTFILE --coverage --coverageReporters=clover --collectCoverageFrom=$FILENAME",
        "coverage_report": "coverage/clover.xml",
        "prefer": "Rely on integration-style tests over isolated unit tests where practical.",
        "rules": [
            "Use Jest (describe/it/expect). Do not introduce a different test runner.",
        ],
    },
    "pytest": {
        "framework": "Python (pytest + coverage.py)",
        "model": "claude-sonnet-5",
        "desired_coverage": 100,
        "test_file": "{dir}/test_{name}.{ext}",
        "test_command": "pytest $TESTFILE --cov=$FILENAME --cov-report=xml:coverage.xml",
        "coverage_report": "coverage.xml",
        "prefer": "",
        "rules": [
            "Use pytest. Do not introduce a different test runner.",
        ],
    },
    "pest": {
        "framework": "Laravel 12 (Pest)",
        "model": "claude-sonnet-5",
        "desired_coverage": 100,
        "test_file": "{dir}/{name}Test.{ext}",
        "test_command": "php artisan test --filter=$TESTNAME --coverage-clover=coverage.xml",
        "coverage_report": "coverage.xml",
        "prefer": "Rely as much as possible on Feature tests instead of Unit tests.",
        "rules": [
            "Use Pest. Always use the Clover-style coverage report; never the HTML report.",
        ],
    },
    "cargo": {
        "framework": "Rust (cargo-llvm-cov)",
        "model": "claude-sonnet-5",
        "desired_coverage": 100,
        "test_file": "{dir}/{name}.{ext}",
        "test_command": "cargo llvm-cov --cobertura --output-path coverage.xml -- $TESTNAME",
        "coverage_report": "coverage.xml",
        "prefer": "Prefer #[cfg(test)] module tests colocated in the file under test.",
        "_note": "Rust coverage is crate-level, not per-file, and cobertura not clover. Per-file 100% is approximate — tune test_command for your crate layout.",
        "rules": [
            "Use the standard #[test] framework. Coverage granularity is crate-level; focus on covering the functions in the file under test.",
        ],
    },
}

CONFIG_DIR = ".undercover-agent"
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
INPUT_PATH = os.path.join(CONFIG_DIR, "input.txt")


def deriveTestFile(filepath, template):
    """Apply {dir}/{name}/{ext} tokens against the file under test."""
    directory = os.path.dirname(filepath)
    base = os.path.basename(filepath)
    name, ext = os.path.splitext(base)
    ext = ext.lstrip(".")
    result = template.replace("{dir}", directory).replace("{name}", name).replace("{ext}", ext)
    # Collapse doubled/leading slashes left when {dir} is empty (file at repo root).
    result = re.sub(r"/+", "/", result).lstrip("/")
    return result


def loadConfig():
    if not os.path.exists(CONFIG_PATH):
        print(f"Error: {CONFIG_PATH} not found.")
        print(f"Scaffold one with: undercover-agent --init <preset>")
        print(f"Presets: {', '.join(PRESETS.keys())}")
        sys.exit(1)
    try:
        with open(CONFIG_PATH, "r") as f:
            cfg = json.load(f)
    except Exception as e:
        print(f"Error: could not parse {CONFIG_PATH}: {e}")
        sys.exit(1)

    required = ("framework", "test_command", "coverage_report", "test_file")
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        print(f"Error: {CONFIG_PATH} is missing required keys: {', '.join(missing)}")
        sys.exit(1)

    cfg.setdefault("desired_coverage", 100)
    cfg.setdefault("prefer", "")
    cfg.setdefault("rules", [])
    cfg.setdefault("timeout_seconds", 1800)
    # "model" is optional: when set, passed to `claude -p --model`; when absent,
    # the headless claude uses its own default model.
    return cfg


def buildPrompt(filepath, cfg):
    testFile = deriveTestFile(filepath, cfg["test_file"])
    testName = os.path.splitext(os.path.basename(testFile))[0]

    testCommand = (
        cfg["test_command"]
        .replace("$TESTFILE", testFile)
        .replace("$TESTNAME", testName)
        .replace("$FILENAME", filepath)
    )

    preferLine = f"\n            - {cfg['prefer']}" if cfg.get("prefer") else ""
    extraRules = "".join(f"\n            - {r}" for r in cfg.get("rules", []))

    prompt = basePrompt
    prompt = prompt.replace("$DESIRED_COVERAGE", str(cfg["desired_coverage"]))
    prompt = prompt.replace("$FRAMEWORK", cfg["framework"])
    prompt = prompt.replace("$PREFER_LINE", preferLine)
    prompt = prompt.replace("$TEST_COMMAND", testCommand)
    prompt = prompt.replace("$COVERAGE_REPORT", cfg["coverage_report"])
    prompt = prompt.replace("$EXTRA_RULES", extraRules)
    prompt = prompt.replace("$FILENAME", filepath)  # last: Target line
    return prompt


def processFile(filepath, cfg):
    filename = os.path.basename(filepath)
    localPrompt = buildPrompt(filepath, cfg)

    # Call Claude Code in non-interactive mode with real-time output
    print(f"Processing {filename} with Claude Code...")
    returncode = None   # None = never spawned / spawn failed (classified as 'failed')
    fail_reason = ""
    try:
        claude_args = ['claude', '-p']
        if cfg.get('model'):
            claude_args += ['--model', cfg['model']]
        for tool in ('Bash(*)', 'Write', 'Read', 'Edit', 'MultiEdit', 'Grep', 'Glob', 'LS'):
            claude_args += ['--allowedTools', tool]
        process = subprocess.Popen(claude_args,
                                   stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE,
                                   text=True,
                                   bufsize=0,
                                   universal_newlines=True)

        # Send prompt via stdin
        process.stdin.write(localPrompt)
        process.stdin.close()

        # Wait for process with timeout while reading output
        import time
        import select

        timed_out = False
        start_time = time.time()
        timeout_seconds = cfg.get('timeout_seconds', 1800)  # per-file cap; skip if a file takes longer

        try:
            while process.poll() is None:
                # Check for timeout
                if time.time() - start_time > timeout_seconds:
                    print(f"\nTimeout expired for {filename}, terminating process...")
                    timed_out = True
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    break

                # Read available output (non-blocking on Unix)
                import sys
                if hasattr(select, 'select'):
                    ready, _, _ = select.select([process.stdout], [], [], 0.1)
                    if ready:
                        line = process.stdout.readline()
                        if line:
                            print(line, end='')
                        else:
                            break
                else:
                    # Fallback for systems without select
                    time.sleep(0.1)

            # Read any remaining output
            if not timed_out:
                for line in process.stdout:
                    print(line, end='')

        except Exception as e:
            print(f"Error during process execution: {e}")
            timed_out = False

        # Capture the outcome for the queue-tracking block below.
        returncode = process.returncode
        if not timed_out and returncode != 0:
            stderr = process.stderr.read()
            fail_reason = stderr.strip().splitlines()[-1] if stderr.strip() else f"exit code {returncode}"
            print(f"Error calling Claude Code for {filename}")
            if stderr:
                print(f"Error output: {stderr}")
    except Exception as e:
        # Spawn failure (e.g. `claude` not on PATH) — `process` may be unbound.
        # returncode stays None so the tracking block classifies this as 'failed'
        # instead of raising NameError on `process.returncode`.
        print(f"Error calling Claude Code for {filename}: {e}")
        fail_reason = str(e)
        timed_out = False  # Treat exceptions as failures, not timeouts

    # Handle queue tracking based on outcome. Classify FIRST, then update files —
    # never remove from input.txt before the outcome is known (that was the
    # silent-drain bug). Do NOT reference `process` here: on a spawn failure it
    # is unbound. Branch on the timed_out / returncode sentinels captured above.
    input_file = INPUT_PATH
    if timed_out:
        outcome = 'timedout'
    elif returncode == 0:
        outcome = 'processed'
    else:
        outcome = 'failed'  # run failure (returncode != 0) OR spawn failure (returncode is None)

    try:
        with open(input_file, 'r') as f:
            lines = f.readlines()

        # Success and timeout are terminal — drop from input.txt so a re-run
        # doesn't reprocess them. Failures STAY in input.txt so a plain re-run
        # retries them, and are also recorded in failed.txt (a durable rerun
        # list carrying the reason).
        if outcome != 'failed':
            with open(input_file, 'w') as f:
                for line in lines:
                    if line.strip() != filepath:
                        f.write(line)
            print(f"\nRemoved {filepath} from input.txt")

        if outcome == 'timedout':
            with open(os.path.join(CONFIG_DIR, 'timedout.txt'), 'a') as f:
                f.write(f"{filepath}\n")
            print(f"Added {filepath} to timedout.txt")
        elif outcome == 'processed':
            with open(os.path.join(CONFIG_DIR, 'processed.txt'), 'a') as f:
                f.write(f"{filepath}\n")
            print(f"Added {filepath} to processed.txt")
        else:  # failed — record with reason, keep in input.txt for re-run
            with open(os.path.join(CONFIG_DIR, 'failed.txt'), 'a') as f:
                f.write(f"{filepath}\t{fail_reason or 'unknown'}\n")
            print(f"Recorded {filepath} in failed.txt (kept in input.txt for re-run)")
    except Exception as e:
        print(f"\nError updating file lists for {filepath}: {e}")


def scaffold(preset):
    if preset not in PRESETS:
        print(f"Error: unknown preset '{preset}'. Available: {', '.join(PRESETS.keys())}")
        sys.exit(1)
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if os.path.exists(CONFIG_PATH):
        print(f"Refusing to overwrite existing {CONFIG_PATH}. Delete it first to re-init.")
    else:
        with open(CONFIG_PATH, "w") as f:
            json.dump(PRESETS[preset], f, indent=2)
            f.write("\n")
        print(f"Wrote {CONFIG_PATH} ({preset} preset). Review the test_command before running.")
    if not os.path.exists(INPUT_PATH):
        open(INPUT_PATH, "a").close()
        print(f"Created empty {INPUT_PATH}. Add one file path per line.")


HELP = """undercover-agent — auto-generate tests to a target coverage, one file at a time.

Usage:
  undercover-agent                 Run: process every path in .undercover-agent/input.txt
  undercover-agent --init <preset> Scaffold .undercover-agent/config.json + input.txt
  undercover-agent --list-presets  List available config presets
  undercover-agent --help          Show this help

Presets: """ + ", ".join(PRESETS.keys()) + """

Config lives in .undercover-agent/config.json (per repo). Placeholders in
test_command: $FILENAME $TESTFILE $TESTNAME. test_file tokens: {dir} {name} {ext}.
"""


def main():
    args = sys.argv[1:]

    if args and args[0] in ("--help", "-h"):
        print(HELP)
        return
    if args and args[0] == "--list-presets":
        for name, p in PRESETS.items():
            print(f"  {name:8s} {p['framework']}")
        return
    if args and args[0] == "--init":
        if len(args) < 2:
            print(f"Error: --init needs a preset. Available: {', '.join(PRESETS.keys())}")
            sys.exit(1)
        scaffold(args[1])
        return

    if not os.path.exists(INPUT_PATH):
        print(f"Error: {INPUT_PATH} not found")
        print(f"Scaffold this repo with: undercover-agent --init <preset>")
        sys.exit(1)

    cfg = loadConfig()
    model_note = cfg.get("model") or "claude default"
    print(f"Framework: {cfg['framework']}  |  model: {model_note}  |  target: {cfg['desired_coverage']}%  |  timeout: {cfg.get('timeout_seconds', 1800)}s/file")

    try:
        with open(INPUT_PATH, 'r') as f:
            for line in f:
                filepath = line.strip()
                if filepath:  # Skip empty lines
                    processFile(filepath, cfg)
    except Exception as e:
        print(f"Error reading file: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
