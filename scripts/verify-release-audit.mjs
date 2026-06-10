import { spawnSync } from 'node:child_process';

const steps = [
  {
    id: 'verify',
    label: '完整本地回归',
    command: 'npm',
    args: ['run', 'verify'],
    required: true,
  },
  {
    id: 'local-smoke',
    label: '本地长篇链路冒烟',
    command: 'npm',
    args: ['run', 'verify:local-smoke'],
    required: true,
  },
  {
    id: 'weicheng-local',
    label: '《围城》原文导入和第 10 章上下文',
    command: '.venv/bin/python',
    args: ['scripts/verify-weicheng-original-continuation.py', '--local-only'],
    required: true,
  },
  {
    id: 'model-preflight',
    label: '当前保存模型配置和 DNS 预检',
    command: 'npm',
    args: ['run', 'verify:model-preflight'],
    required: true,
  },
];

function runStep(step) {
  console.log(`\n[verify-release-audit] ${step.label}`);
  console.log(`[verify-release-audit] command: ${[step.command, ...step.args].join(' ')}`);
  const started = performance.now();
  const result = spawnSync(step.command, step.args, {
    cwd: process.cwd(),
    env: process.env,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  if (result.stdout) {
    process.stdout.write(result.stdout);
  }
  if (result.stderr) {
    process.stderr.write(result.stderr);
  }
  const elapsed = Math.round(performance.now() - started) / 1000;
  return {
    id: step.id,
    label: step.label,
    command: [step.command, ...step.args].join(' '),
    status: result.status === 0 ? 'passed' : 'failed',
    exitCode: result.status,
    elapsed,
    required: step.required,
  };
}

const results = steps.map(runStep);
const failed = results.filter((item) => item.required && item.status !== 'passed');
const summary = {
  status: failed.length === 0 ? 'passed' : 'failed',
  results,
  blockedBy: failed.map((item) => item.id),
  note:
    failed.length === 0
      ? '本地回归、长篇本地链路、原文导入上下文和模型预检均通过。'
      : '存在未通过的发布前检查；不要把当前状态判定为可上线。',
};

console.log('\n[verify-release-audit] summary');
console.log(JSON.stringify(summary, null, 2));

if (failed.length > 0) {
  process.exitCode = 1;
}
