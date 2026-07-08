<img src="img/logo.png" alt="Undercover Agent Logo" width="700px">

# Undercover agent
> **Let's have AI agents write the tests our engineers didn't have the time for.**

Software developers know they should write unit tests. Shipping features, however, always seems more important. Over time, technical debt creeps in, and by the time we want to pay it back, we really, really wish we had those tests.

Writing unit tests for an existing codebase usually isn't simple, and it's never cheap.

But, what if we could generate these tests instead of dedicating development capacity to them? Can we get an LLM to write tests so our engineers don't have to?

LLMs can write test automation. That's not new. But telling Cursor to write a test for a component we just created takes almost as long as writing the test ourselves. It still requires a human developer. The performance gains are minimal.

What I am interested in is asking it to write **all the missing tests** for a codebase!

Automated tests execute parts of the codebase and check whether they behave as expected. If a codebase has 100 lines of code and our test suite executes 40 of those, we say the code has 40% code coverage. Most modern programming environments allow us to generate reports showing us which lines of code have been tested and, more importantly, which lines have not.

Undercover Agent is an experiment to figure out if we can get our favourite AI Code Agents to write the tests for us.

## Usage
To generate tests for a single class, feed the prompt found in `src/cover_one_file.prompt` into your favourite agent framework. I ran the experiment with [Cursor](https://cursor.sh), [Junie](https://www.jetbrains.com/junie/), [Codex](https://github.com/openai/codex) and [Claude Code](https://claude.ai). Claude Code by far has the best results in my experience.

To generate tests for multiple classes using Claude Code, use the script in `src/undercover-agent.py` like this:

- make sure Python >3.12 and Claude Code are installed
- copy the script into the codebase you want to cover
- scaffold a config for your test framework: `python undercover-agent.py --init <preset>` (presets: `vitest`, `jest`, `pytest`, `pest`, `cargo`). This writes `.undercover-agent/config.json`; review `test_command` and `coverage_report` so they match how your project runs coverage.
- fill `.undercover-agent/input.txt` with the relative paths of the files you want to cover, one per row. (Tip: you can ask Claude Code to do this for you.)
- execute the script by running `python undercover-agent.py`

The script reads the first line from `input.txt`, generates test code for that file, then moves it out of `input.txt` (to `processed.txt`, `timedout.txt`, or `failed.txt`) and takes the next one. Failures stay queued for a plain re-run.

The framework was originally hard-wired to Laravel/Pest; it now comes from `.undercover-agent/config.json`, so the same loop covers any stack that can emit a coverage report. Run `python undercover-agent.py --list-presets` to see the built-ins.

Some helpful insights and lessons learned can be found [here](/LessonsLearned.md).
## Help wanted
For now, it's just a prompt and a set of articles. But if enough people chip in, we might build the tool that can help us fight technical debt on all legacy code bases.

So, try running the prompt over your own code bases and add your experiences to this repository. 

Let's take code coverage to 100%.

## Learn more
For more details about the original experiment and its results, check out [this article](https://somethingwithai.substack.com/p/from-0-to-319-in-25-minutes-and-263).
