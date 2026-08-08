'use strict';

const REQUIRED_WORKFLOWS = Object.freeze(['DOR CI', 'CodeQL Advanced']);
const COMMENT_MARKER = '<!-- dor-pr-ci-watch -->';

function compareRuns(left, right) {
  const attemptDelta = (left.run_attempt ?? 1) - (right.run_attempt ?? 1);
  if (attemptDelta !== 0) {
    return attemptDelta;
  }
  return (left.id ?? 0) - (right.id ?? 0);
}

function latestRequiredRuns(runs, headSha, requiredWorkflows = REQUIRED_WORKFLOWS) {
  const required = new Set(requiredWorkflows);
  const latest = new Map();

  for (const run of runs) {
    if (
      !required.has(run.name) ||
      run.event !== 'pull_request' ||
      run.head_sha !== headSha
    ) {
      continue;
    }

    const current = latest.get(run.name);
    if (!current || compareRuns(run, current) > 0) {
      latest.set(run.name, run);
    }
  }

  return latest;
}

function evaluateRuns(runs, headSha, requiredWorkflows = REQUIRED_WORKFLOWS) {
  const latest = latestRequiredRuns(runs, headSha, requiredWorkflows);
  const missing = requiredWorkflows.filter((name) => !latest.has(name));
  const pending = requiredWorkflows.filter(
    (name) => latest.has(name) && latest.get(name).status !== 'completed',
  );

  if (missing.length > 0 || pending.length > 0) {
    return { ready: false, missing, pending, runs: latest };
  }

  const completedRuns = requiredWorkflows.map((name) => latest.get(name));
  return {
    ready: true,
    missing: [],
    pending: [],
    passed: completedRuns.every((run) => run.conclusion === 'success'),
    runs: latest,
  };
}

function resultLabel(conclusion) {
  return conclusion === 'success' ? '✅ success' : `❌ ${conclusion ?? 'unknown'}`;
}

function renderComment(evaluation, headSha, requiredWorkflows = REQUIRED_WORKFLOWS) {
  if (!evaluation.ready) {
    throw new Error('Cannot render a CI result before every required workflow is complete.');
  }

  const shortSha = headSha.slice(0, 7);
  const heading = evaluation.passed
    ? `✅ All required CI workflows passed for \`${shortSha}\`.`
    : `❌ One or more required CI workflows failed for \`${shortSha}\`.`;
  const rows = requiredWorkflows.map((name) => {
    const run = evaluation.runs.get(name);
    return `| ${name} | ${resultLabel(run.conclusion)} | [#${run.run_number}](${run.html_url}) |`;
  });

  return [
    COMMENT_MARKER,
    heading,
    '',
    '| Workflow | Result | Run |',
    '|---|---|---|',
    ...rows,
    '',
    '_Repository-native notification from `PR CI Watch`._',
  ].join('\n');
}

async function pullRequestNumbers(github, owner, repo, workflowRun) {
  const eventNumbers = (workflowRun.pull_requests ?? [])
    .map((pullRequest) => pullRequest.number)
    .filter(Number.isInteger);

  if (eventNumbers.length > 0) {
    return [...new Set(eventNumbers)];
  }

  const response = await github.rest.repos.listPullRequestsAssociatedWithCommit({
    owner,
    repo,
    commit_sha: workflowRun.head_sha,
  });
  return [...new Set(response.data.map((pullRequest) => pullRequest.number))];
}

async function upsertComment(github, owner, repo, issueNumber, body) {
  const comments = await github.paginate(github.rest.issues.listComments, {
    owner,
    repo,
    issue_number: issueNumber,
    per_page: 100,
  });
  const existing = comments.find((comment) => comment.body?.includes(COMMENT_MARKER));

  if (existing?.body === body) {
    return 'unchanged';
  }
  if (existing) {
    await github.rest.issues.updateComment({
      owner,
      repo,
      comment_id: existing.id,
      body,
    });
    return 'updated';
  }

  await github.rest.issues.createComment({
    owner,
    repo,
    issue_number: issueNumber,
    body,
  });
  return 'created';
}

async function run({ github, context, core }) {
  const workflowRun = context.payload.workflow_run;
  if (!workflowRun || workflowRun.event !== 'pull_request') {
    core.info('Ignoring a workflow run that was not triggered by a pull request.');
    return;
  }

  const { owner, repo } = context.repo;
  const runs = await github.paginate(github.rest.actions.listWorkflowRunsForRepo, {
    owner,
    repo,
    head_sha: workflowRun.head_sha,
    event: 'pull_request',
    per_page: 100,
  });
  const evaluation = evaluateRuns(runs, workflowRun.head_sha);

  if (!evaluation.ready) {
    core.info(
      `CI is not terminal: missing=${evaluation.missing.join(',') || 'none'}; ` +
        `pending=${evaluation.pending.join(',') || 'none'}.`,
    );
    return;
  }

  const numbers = await pullRequestNumbers(github, owner, repo, workflowRun);
  if (numbers.length === 0) {
    core.warning(`No pull request is associated with ${workflowRun.head_sha}.`);
    return;
  }

  const body = renderComment(evaluation, workflowRun.head_sha);
  for (const issueNumber of numbers) {
    const result = await upsertComment(github, owner, repo, issueNumber, body);
    core.info(`${result} CI summary comment on PR #${issueNumber}.`);
  }
}

module.exports = {
  COMMENT_MARKER,
  REQUIRED_WORKFLOWS,
  evaluateRuns,
  latestRequiredRuns,
  renderComment,
  run,
  upsertComment,
};
