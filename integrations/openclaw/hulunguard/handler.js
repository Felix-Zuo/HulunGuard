const REMINDER_NAME = 'HULUNGUARD_MONITOR.md';
const REMINDER_PATH = REMINDER_NAME;

const REMINDER_CONTENT = `
## HulunGuard Monitor

For long-running, artifact-producing, research-heavy, or compaction-prone work, use HulunGuard.

Project CLI:
\`python -m hulun_guard\` or \`hulun\` after installing HulunGuard.

Minimum protocol:
- Start monitor: \`python -m hulun_guard open --conversation "<short name>" --group "<project>" --widget\`
- Track evidence: \`python -m hulun_guard record-evidence --root "<project-root>" --kind test --summary "<proof>" --command "<command>"\`
- Check risk: \`python -m hulun_guard scan --root "<project-root>"\`
- Final gate: \`python -m hulun_guard verify --root "<project-root>"\`

If HulunGauge is red or verify fails, do not claim completion. Recover state, add evidence, or tell the user what is missing.
`.trim();

function isObject(value) {
  return !!value && typeof value === 'object';
}

function isInjectedReminderFile(value) {
  return isObject(value) && value.path === REMINDER_PATH && (value.virtual === true || value.content === REMINDER_CONTENT);
}

const handler = async (event) => {
  if (!event || typeof event !== 'object') return;
  if (event.type !== 'agent' || event.action !== 'bootstrap') return;
  if (!event.context || typeof event.context !== 'object') return;

  const sessionKey = event.sessionKey || '';
  if (sessionKey.includes(':subagent:')) return;

  if (Array.isArray(event.context.bootstrapFiles)) {
    const occupiedByOtherFile = event.context.bootstrapFiles.some(
      (file) => isObject(file) && file.path === REMINDER_PATH && !isInjectedReminderFile(file),
    );
    if (occupiedByOtherFile) return;

    const cleanedBootstrapFiles = event.context.bootstrapFiles.filter(
      (file, index, files) =>
        !isInjectedReminderFile(file) ||
        files.findIndex((candidate) => isInjectedReminderFile(candidate)) === index,
    );

    const reminderFile = {
      name: REMINDER_NAME,
      path: REMINDER_PATH,
      content: REMINDER_CONTENT,
      missing: false,
      virtual: true,
    };

    const existingIndex = cleanedBootstrapFiles.findIndex((file) => isInjectedReminderFile(file));
    if (existingIndex === -1) {
      cleanedBootstrapFiles.push(reminderFile);
    } else {
      cleanedBootstrapFiles[existingIndex] = reminderFile;
    }

    event.context.bootstrapFiles = cleanedBootstrapFiles;
  }
};

module.exports = handler;
module.exports.default = handler;
