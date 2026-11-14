# Where an LLM product burns money

Used by [checklist.md](checklist.md) section G when the design has a webhook, a queue or a
background worker between the user and the model call. Each leak below is quiet: the feature
works, the tests pass, and the bill grows. Each one comes with the check that catches it.

## 1. Quota checked at the door, charged in the worker

The request handler checks that the user has quota left and enqueues a job; the worker spends
the tokens and decrements the quota later. Ten requests that arrive together all pass the
check before any of them is charged.

**Check:** the quota is reserved atomically when the job is accepted (a conditional update or a
row lock, not a read then a write) and settled or released when the job ends. A test fires N
concurrent requests against a quota of 1 and asserts that exactly one job runs.

## 2. Output re-entering its own trigger

The app posts a reply, writes a file or sends an email, and that event fires the same webhook
or queue that started the job. Each answer starts another paid run.

**Check:** everything the app writes is marked as its own (an author id, a header, a flag in
the payload), and the trigger drops marked events before any model call. A test replays the
app's own output into the trigger and asserts zero model calls.

## 3. A free tier reaching the expensive path

The plan gate sits in the UI or the API handler, while a retry, a fallback, a background
re-run or an admin tool calls the expensive model without asking which plan the user is on.

**Check:** the model for each call is chosen from the user's plan at the place the call is
made, not passed down from the door. A test runs every entry point (request, retry, fallback,
scheduled job) as a free user and asserts which model was called.

## 4. Retrying failures that will fail again

A retry loop that treats every error the same pays again for a request the provider already
refused: a context that is too long, a malformed tool schema, a content-policy refusal, a
parse error on output that will be the same next time.

**Check:** retries are limited to transient causes (rate limits, server errors, timeouts that
were reconciled, see below), with a cap. Each deterministic error class has a test asserting
one call and no retry.

## 5. Tokens spent before the step that can still fail

The model call runs first, then the result is saved, charged or delivered. When that later
step fails (a database write, an upload, a schema check), the job is retried from the start
and the model call is paid again.

**Check:** the steps that can fail cheaply (validation, permission, storage reachable) run
before the model call, and a model result is stored as soon as it arrives, keyed by the job, so
a retry reuses it instead of calling again. A test fails the step after the call and asserts
that the retry makes no second model call.

## An ambiguous timeout is not a failure yet

A timeout from the provider does not say whether the call ran. Retrying it as a new job may pay
twice and, with tools, act twice. Record the job as "outcome unknown", reconcile it first (the
provider's request id, a usage or batch status lookup, an idempotency key the provider honours,
or the side effect itself), and retry only once it is known not to have completed.

**Check:** a test makes the provider time out after doing the work and asserts that no second
paid call and no second side effect follow before reconciliation.
