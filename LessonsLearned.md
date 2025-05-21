<img src="img/logo.png" alt="Undercover Agent Logo" width="700px">

# Lessons Learned

Writing unit tests isn't always as straightforward. Generating them isn't either. Here are a few lessons learned while trying to get the agent to work.

## Keep coverage reports small
The original experiment relied on reading the HTML coverage report. But as soon as you tested more than a handful of classes, that HTML file became too big for Claude's context window. If the agent cannot ingest the coverage report, it cannot know which parts of the code still need testing. A much better way forward is to rely on the old-school clover.xml reports, which are a lot more concise.

## Do one file at a time
Originally, I set out to generate all coverage at once. The problem is that, as the agent adds more tests, the execution of the entire test suite takes longer and longer. So, by covering one file at a time, we can significantly speed up the process.

## Make files easy to test
My original test code base had a controller that interacted directly with the Google Calendar SDK. That made it really hard to write unit tests as mocking that SDK isn't trivial. By moving that interaction to a GoogleCalendarService class, mocking the external interactions became easier. Direct usage of SDKs or applying the Service Locator Pattern makes things hard to test. That's true when humans write unit tests and that's true for agents as well. Good patterns like dependency injection make testing easier.

If your agents struggle to add tests, try making that part of the code more testable by refactoring.

## It's not all or nothing
I started this experiment with a class that didn't have a single test and got to 100% code coverage. But if your codebase has 40% code coverage, the prompt should also work to take it up from there.

100% code coverage might be too much of a good thing as well. Maybe aim for 80% to get started?