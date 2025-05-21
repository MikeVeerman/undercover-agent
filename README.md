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
Feed the prompt found in `src/cover_one_file.prompt` into your favourite agent framework. I ran the experiment with [Cursor](https://cursor.sh), [Junie](https://www.jetbrains.com/junie/), [Codex](https://github.com/openai/codex) and [Claude Code](https://claude.ai).

Some helpful insights and lessons learned can be found [here](/LessonsLearned.md).
## Help wanted
For now, it's just a prompt and a set of articles. But if enough people chip in, we might build the tool that can help us fight technical debt on all legacy code bases.

So, try running the prompt over your own code bases and add your experiences to this repository. 

Let's take code coverage to 100%.

## Learn more
For more details about the original experiment and its results, check out [this article](https://somethingwithai.substack.com/p/from-0-to-319-in-25-minutes-and-263).
