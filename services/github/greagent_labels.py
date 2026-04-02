"""Greagent GitHub labels for issue and PR workflows (queue, progress, outcome)."""

# Issue + PR coder queue (issues: ``issues`` webhook; PRs: ``pull_request`` ``labeled`` only).
CODE = "greagent:code"
IN_PROGRESS = "greagent:in-progress"
DONE = "greagent:done"
ERROR = "greagent:error"

# Pull request workflow
REVIEW = "greagent:review"
REVIEWING = "greagent:reviewing"
REVIEWED = "greagent:reviewed"
