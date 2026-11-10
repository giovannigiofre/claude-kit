# Standing loops

kit.json `lead.loops`, e.g. `{"name": "tend-prs", "every": "10m", "run": "tend the threads' open
PRs: failed CI, review comments, merge conflicts"}`. Write the task in words: a scheduled prompt
cannot invoke a user-only skill such as `/kit:go`. Create the missing ones with CronCreate after
checking CronList; they are session-only, expire after 7 days and fire only while the session is
idle (say so). When one fires, hand its work to a background thread and reply in one line.
