#!/usr/bin/env python3
# Filter the output of a build command for errors that should be ignored as
# likely reflecting known limitations of 3C bounds inference.
#
# usage: BUILD_COMMAND 2>&1 | filter-bounds-inference-errors.py
#
# Exits 1 if the input contains errors that should not be ignored. For this to
# be useful, the original pipeline should be run with `pipefail` off.

# This could likely be implemented as a shell script using `sed`, etc., but it
# looked like it might become messy. Once I took the plunge to Python, I didn't
# regret it: I find the Python much clearer. ~ Matt

import re
import sys

ERROR_LINE_RE = re.compile(r'^(.*): error: (.*)$')
FILTER_RE = re.compile(r'expression has unknown bounds')

saw_unfiltered_error = False
# This gives the same result as `sys.stdin.readlines()` (which I normally find
# more explicit) but processes lines as they are received, which is nice for
# long-running builds.
for line in sys.stdin:
    line = line.rstrip('\n')
    match = ERROR_LINE_RE.search(line)
    if match is not None:
        is_filtered = (FILTER_RE.search(match[2]) is not None)
        if is_filtered:
            line = ERROR_LINE_RE.sub(r'\1: error (filtered): \2', line)
        else:
            saw_unfiltered_error = True
    # It probably makes more sense to write what was originally stderr output to
    # stderr rather than make all callers redirect it, even if unix convention
    # would normally be that the main data we process should go to stdout.
    sys.stderr.write(line + '\n')

sys.exit(1 if saw_unfiltered_error else 0)
