'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const {
  COMMENT_MARKER,
  evaluateRuns,
  renderComment,
  upsertComment,
} = require('./ci_watch.js');

const HEAD_SHA = '0123456789abcdef0123456789abcdef01234567';

function workflowRun(name, overrides = {}) {
  return {
    id: name === 'DOR CI' ? 10 : 20,
    name,
    event: 'pull_request',
    head_sha: HEAD_SHA,
    status: 'completed',
    conclusion: 'success',
    run_attempt: 1,
    run_number: name === 'DOR CI' ? 157 : 88,
    html_url: `https://github.com/example/repo/actions/runs/${name === 'DOR CI' ? 10 : 20}`,
    ...overrides,
  };
}

test('waits until every required workflow exists and is complete', () => {
  const missing = evaluateRuns([workflowRun('DOR CI')], HEAD_SHA);
  assert.equal(missing.ready, false);
  assert.deepEqual(missing.missing, ['CodeQL Advanced']);

  const pending = evaluateRuns(
    [workflowRun('DOR CI'), workflowRun('CodeQL Advanced', { status: 'in_progress' })],
    HEAD_SHA,
  );
  assert.equal(pending.ready, false);
  assert.deepEqual(pending.pending, ['CodeQL Advanced']);
});

test('ignores unrelated events and commit SHAs', () => {
  const result = evaluateRuns(
    [
      workflowRun('DOR CI'),
      workflowRun('CodeQL Advanced', { event: 'push' }),
      workflowRun('CodeQL Advanced', { head_sha: 'f'.repeat(40) }),
    ],
    HEAD_SHA,
  );
  assert.equal(result.ready, false);
  assert.deepEqual(result.missing, ['CodeQL Advanced']);
});

test('uses the latest attempt when a workflow is rerun', () => {
  const result = evaluateRuns(
    [
      workflowRun('DOR CI', { id: 30, conclusion: 'failure', run_attempt: 1 }),
      workflowRun('DOR CI', { id: 31, conclusion: 'success', run_attempt: 2 }),
      workflowRun('CodeQL Advanced'),
    ],
    HEAD_SHA,
  );
  assert.equal(result.ready, true);
  assert.equal(result.passed, true);
  assert.equal(result.runs.get('DOR CI').id, 31);
});

test('renders a stable failure summary with an idempotency marker', () => {
  const evaluation = evaluateRuns(
    [workflowRun('DOR CI'), workflowRun('CodeQL Advanced', { conclusion: 'failure' })],
    HEAD_SHA,
  );
  const body = renderComment(evaluation, HEAD_SHA);

  assert.match(body, new RegExp(COMMENT_MARKER));
  assert.match(body, /One or more required CI workflows failed/);
  assert.match(body, /\| CodeQL Advanced \| ❌ failure \|/);
});

test('creates, updates, and preserves the single watcher comment', async () => {
  const calls = [];
  let comments = [];
  const github = {
    paginate: async () => comments,
    rest: {
      issues: {
        listComments: () => {},
        createComment: async (payload) => calls.push(['create', payload]),
        updateComment: async (payload) => calls.push(['update', payload]),
      },
    },
  };

  assert.equal(await upsertComment(github, 'example', 'repo', 28, 'first'), 'created');
  comments = [{ id: 7, body: `${COMMENT_MARKER}\nold` }];
  assert.equal(
    await upsertComment(github, 'example', 'repo', 28, `${COMMENT_MARKER}\nnew`),
    'updated',
  );
  comments = [{ id: 7, body: `${COMMENT_MARKER}\nnew` }];
  assert.equal(
    await upsertComment(github, 'example', 'repo', 28, `${COMMENT_MARKER}\nnew`),
    'unchanged',
  );
  assert.deepEqual(
    calls.map(([operation]) => operation),
    ['create', 'update'],
  );
});
