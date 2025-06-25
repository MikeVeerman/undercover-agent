#!/usr/bin/env python3

import os
import sys
import subprocess

basePrompt = """I am the owner of a legacy code base and I want to increase its quality and security. This is a commercial product that's used by paying customers and I want to make sure the quality is there. I own all files that will be handled by the prompt.
            You are an agent who will cover a component with code coverage. You will work on the component until you reach the desired level of code coverage.

            Target:
            - We will work on testing this file: $FILENAME. This is called the "file under test".
            - The desired level of code coverage is 100%

            Language-specific rules:
            - We are testing a Laravel 12 app
            - We will rely as much as possible on Feature tests instead of Unit tests.
            - We use Pest for testing
            - Command to test the file under test and generate the code coverage report for the file under test: php artisan test --filter=$TESTFILENAME --coverage-clover=coverage.xml
            - Always use the Clover-style coverage report. Never use the HTML style report.

            Rules:
            - Don't touch the file under test. Only touch the test code.
            - Each test has three steps marked by comments:
            	1. GIVEN: Set up the environment and variables needed to run the test
            	2. WHEN: Execute one of the functions in the file under test with the values set in GIVEN
            	3. THEN: Assert that the outcome of the test matches the expected behaviour
            - Never write a test that doesn't have the three GIVEN/WHEN/THEN steps
            - Add one unit test method, at a time. Iterate over it until it works.
            - Only run tests for the file under test. Never run the whole test suite.

            Setup:
            -Your first task will be to run the tests for the file under test
            -If there are no tests, create a test that tests the constructor.

            Main task:
            Step 1: Generate the code coverage report for the file under test.
            Step 2: Read the code coverage report and list the parts of the code that are not covered in tests as a numbered list.
            Step 3: Log to the console: "The file under test currently has X% code coverage", where X is the coverage as mentioned in the coverage report.
            Step 4: If X is equal or higher than the desired level of code coverage, stop the agent.
            Step 5: Take the first item of the numbered list and add a test that covers it to the unit test file.
            Step 6: Run the newly created test to see if it works. If it doesn't pass, see why it fails and adapt. Run the test again. Repeat step 4 until the test passes.

            After completing step 6, loop over steps 1, 2, 3, 4, 5 and 6 until the desired level of code coverage is reached."""


def processFile(filepath):
    filename = os.path.basename(filepath)
    name, ext = os.path.splitext(filename)
    testFile = name + 'Test' + ext
    localPrompt = basePrompt.replace('$FILENAME', filepath).replace('$TESTFILENAME', testFile)

    # Call Claude Code in non-interactive mode with real-time output
    print(f"Processing {filename} with Claude Code...")
    try:
        process = subprocess.Popen(['claude',
                                    '--allowedTools', 'Bash(*)',
                                    '--allowedTools', 'Write',
                                    '--allowedTools', 'Read',
                                    '--allowedTools', 'Edit',
                                    '--allowedTools', 'MultiEdit',
                                    '--allowedTools', 'Grep',
                                    '--allowedTools', 'Glob',
                                    '--allowedTools', 'LS'],
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
        timeout_seconds = 1800  # 30 minutes timeout. If it takes longer than half an hour to get the tests working, skip it

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

        # Check for errors
        if process.returncode != 0:
            stderr = process.stderr.read()
            print(f"Error calling Claude Code for {filename}")
            if stderr:
                print(f"Error output: {stderr}")
    except Exception as e:
        print(f"Error calling Claude Code for {filename}: {e}")
        timed_out = False  # Treat exceptions as failures, not timeouts

    # Handle file tracking based on outcome
    input_file = '.undercover-agent/input.txt'

    try:
        # Read current input file
        with open(input_file, 'r') as f:
            lines = f.readlines()

        # Remove the processed filepath from input.txt
        with open(input_file, 'w') as f:
            for line in lines:
                if line.strip() != filepath:
                    f.write(line)

        if timed_out:
            # Add to timedout.txt
            with open('.undercover-agent/timedout.txt', 'a') as f:
                f.write(f"{filepath}\n")
            print(f"\nAdded {filepath} to timedout.txt")
        elif process.returncode == 0:
            # Add to processed.txt (successful completion)
            with open('.undercover-agent/processed.txt', 'a') as f:
                f.write(f"{filepath}\n")
            print(f"\nAdded {filepath} to processed.txt")
        else:
            # Process failed but didn't timeout - could add to a failed.txt if needed
            print(f"\nProcess failed for {filepath} (exit code: {process.returncode})")

        print(f"Removed {filepath} from input.txt")
    except Exception as e:
        print(f"\nError updating file lists for {filepath}: {e}")


def main():
    input_file = '.undercover-agent/input.txt'

    if not os.path.exists(input_file):
        print(f"Error: {input_file} not found")
        sys.exit(1)

    try:
        with open(input_file, 'r') as f:
            for line in f:
                filepath = line.strip()
                if filepath:  # Skip empty lines
                    processFile(filepath)
    except Exception as e:
        print(f"Error reading file: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
