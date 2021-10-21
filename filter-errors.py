#!/usr/bin/env python3
# Filter the output of a build command for errors that should be ignored as
# likely reflecting known limitations of 3C.
#
# usage: BUILD_COMMAND 2>&1 | filter-errors.py
#
# Exits 1 if the input contains errors that should not be ignored. For this to
# be useful, the original pipeline should be run with `pipefail` off.
#
# This script uses a csv database, defaulting to "benchmark_errors.csv" in the
# current directory. Multiple databases can be loaded by adding them as
# arguments to the script. Non-existing files will be ignored.
#
# The database consists of "category,tag,regex,note". Errors are matched
# by regex and assigned the related tag. A tag's category determines whether
# it counts as an error or is ignored. Notes are printed out by their tag
# in the final summary.
#
# Earlier entries will override later entries, both in tag and in the tag's
# category. That means that if two regexes match an error, the first will
# have the tag that is reported. If an earlier entry has a different
# category for a tag, that category will be used for all instances of the tag.
#

import re
import sys
import csv

# initialize counters and compile regexes
ERROR_LINE_RE = re.compile(r'^(.*): error: (.*)$')
error_count_by_tag = {}
acceptable_categories = {'ignore','bounds','inprogress'}
filter_rules = []
database_files = sys.argv[1:]
database_files.append("benchmark_errors.csv")
for file in database_files:
    try:
        with open(file,'r') as errors:
            filter_rules.extend([line for line in csv.DictReader(errors)])
    except FileNotFoundError:
        pass
# final default error
filter_rules.append({'category': "error", 'tag':"UNKNOWN_ERROR", 'regex':".*", "note":""})
for line in filter_rules:
    line['RE'] = re.compile(line['regex'])
    error_count_by_tag[line['tag']] = 0

# read through errors incrementally, keeping stats
for line in sys.stdin:
    line = line.rstrip('\n')
    at_error_match = ERROR_LINE_RE.search(line)
    if at_error_match is not None:
        for error in filter_rules:
            if (error['RE'].search(at_error_match[2]) is not None):
                line = ERROR_LINE_RE.sub(r'\1: error ({}): \2'.format(error['tag']), line)
                error_count_by_tag[error['tag']] += 1
                break
    # It probably makes more sense to write what was originally stderr output to
    # stderr rather than make all callers redirect it, even if unix convention
    # would normally be that the main data we process should go to stdout.
    sys.stderr.write(line + '\n')
# finalize stderr before writing to stdout for viewers that may interleave
sys.stderr.flush()

# print out stats
output_tags = set()
unacceptable_error_count = 0
print('Benchmark error report:')
for e in filter_rules:
    if (e['tag'] in output_tags) or (error_count_by_tag[e['tag']] == 0): continue
    output_tags.add(e['tag'])
    if e['category'] in acceptable_categories:
        category = "(" + e['category'] + ")"
    else:
        unacceptable_error_count += error_count_by_tag[e['tag']]
        category = "(error)"
    print('  {0} {1}: {2}     {3}'.format(category,e['tag'],error_count_by_tag[e['tag']],e['note']))
if unacceptable_error_count > 0:
    print("Benchmark failed - {} errors not acceptable".format(unacceptable_error_count))
    sys.exit(1)
else:
    print("Benchmark succeeded - all errors acceptable")
    sys.exit(0)

