#!/usr/bin/env node

/**
 * Enhanced AgentsMail bulk sender
 * Features:
 * - Personalization via CSV (header row; column "email" required)
 * - Attachments support (multipart/form-data)
 * - Persistent JSONL logging and resume-on-failure
 * - Dry-run mode
 *
 * Dependencies:
 *   npm install dotenv minimist form-data csv-parse
 *
 * Usage examples:
 *   node scripts/send-bulk-agentsmail.js --csv recipients.csv --subject subject.txt --html letter.html --attachments-dir ./attachments --batch 5
 *   node scripts/send-bulk-agentsmail.js --emails emails.txt --subject subject.txt --html letter.html --dry
 */

const fs = require('fs');
const fsp = fs.promises;
const path = require('path');

require('dotenv').config();

const argv = require('minimist')(process.argv.slice(2));
const FormData = require('form-data');
const { parse } = require('csv-parse/sync');

const emailsPath = argv.emails || argv.e || 'emails.txt';
const csvPath = argv.csv || argv.c || null; // CSV for personalization
const subjectPath = argv.subject || argv.s || 'subject.txt';
const htmlPath = argv.html || argv.h || 'letter.html';
const attachmentsDir = argv['attachments-dir'] || argv.a || null;
const batchSize = Number(process.env.BATCH_SIZE || argv.batch || 1);
let delayMs = Number(process.env.DELAY_MS || argv.delay || 1000);
const maxRetries = Number(process.env.MAX_RETRIES || argv.retries || 5);
const dryRun = argv.dry || argv.dryrun || false;
const resume = argv.resume || false;
const logPath = argv.log || 'logs/send-log.jsonl';

const {
  AGENTSMAIL_API_KEY,
  AGENTSMAIL_BASE_URL,
  AGENTSMAIL_MAILBOX,
  AGENTSMAIL_MAILBOX_NAME,
  AGENTSMAIL_SEND_ENDPOINT = '/api/send'
} = process.env;

if (!AGENTSMAIL_API_KEY || !AGENTSMAIL_BASE_URL || !AGENTSMAIL_MAILBOX) {
  console.error('Missing one of required env vars: AGENTSMAIL_API_KEY, AGENTSMAIL_BASE_URL, AGENTSMAIL_MAILBOX');
  process.exit(1);
}

// AgentsMail rate limit: 60 sends / minute per mailbox
const minDelayMs = Math.ceil((60_000 / 60) * (batchSize)); // batchSize * 1000
if (delayMs < minDelayMs) {
  console.warn(`Adjusting delay to meet AgentsMail rate limits: batchSize=${batchSize} => delay >= ${minDelayMs}ms`);
  delayMs = minDelayMs;
}

function sleep(ms) {
  return new Promise((res) => setTimeout(res, ms));
}

function isEmail(s) {
  return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(String(s || '').trim());
}

async function ensureLogsDir() {
  const dir = path.dirname(logPath);
  await fsp.mkdir(dir, { recursive: true });
}

async function appendLog(entry) {
  await ensureLogsDir();
  const line = JSON.stringify(entry) + '\n';
  await fsp.appendFile(logPath, line, 'utf8');
}

async function loadSentSet() {
  // Read log file and build set of emails with success
  const sent = new Set();
  try {
    const data = await fsp.readFile(logPath, 'utf8');
    for (const line of data.split(/\r?\n/)) {
      if (!line.trim()) continue;
      try {
        const obj = JSON.parse(line);
        if (obj.email && obj.status === 'success') sent.add(obj.email);
      } catch (e) {
        // ignore
      }
    }
  } catch (e) {
    // no log yet
  }
  return sent;
}

function renderTemplate(template, vars) {
  // Replace {{field}} with vars[field]
  return String(template).replace(/{{\s*([a-zA-Z0-9_\-]+)\s*}}/g, (m, key) => {
    if (Object.prototype.hasOwnProperty.call(vars, key)) return String(vars[key]);
    return '';
  });
}

async function loadFiles() {
  const subjectRaw = await fsp.readFile(path.resolve(subjectPath), 'utf8');
  const htmlRaw = await fsp.readFile(path.resolve(htmlPath), 'utf8');

  let recipients = [];

  if (csvPath) {
    const csvRaw = await fsp.readFile(path.resolve(csvPath), 'utf8');
    const records = parse(csvRaw, { columns: true, skip_empty_lines: true });
    // Expect a column named 'email'
    recipients = records.map((r) => ({ ...r, email: String(r.email || '').trim() }));
    recipients = recipients.filter((r) => isEmail(r.email));
  } else {
    const emailsRaw = await fsp.readFile(path.resolve(emailsPath), 'utf8');
    recipients = emailsRaw
      .split(/\r?\n/)
      .map((l) => ({ email: l.trim() }))
      .filter((r) => r.email && isEmail(r.email));
  }

  const subject = subjectRaw.split(/\r?\n/).find(Boolean) || '';
  const html = htmlRaw;

  return { recipients, subject, html };
}

async function collectAttachmentStreams() {
  if (!attachmentsDir) return null;
  const dir = path.resolve(attachmentsDir);
  let files = [];
  try {
    const entries = await fsp.readdir(dir, { withFileTypes: true });
    for (const e of entries) {
      if (e.isFile()) files.push(path.join(dir, e.name));
    }
  } catch (e) {
    console.warn('Could not read attachments directory', e.message);
    return null;
  }
  return files;
}

async function sendMail(recipientEmail, subject, html, attachmentsFiles) {
  const url = AGENTSMAIL_BASE_URL.replace(/\/$/, '') + AGENTSMAIL_SEND_ENDPOINT;

  if (dryRun) {
    return { ok: true, dryRun: true, payload: { mailbox: AGENTSMAIL_MAILBOX, mailbox_name: AGENTSMAIL_MAILBOX_NAME, to: recipientEmail, subject, html, attachments: (attachmentsFiles || []) } };
  }

  if (attachmentsFiles && attachmentsFiles.length > 0) {
    // multipart/form-data
    const form = new FormData();
    form.append('mailbox', AGENTSMAIL_MAILBOX);
    if (AGENTSMAIL_MAILBOX_NAME) form.append('mailbox_name', AGENTSMAIL_MAILBOX_NAME);
    form.append('to', recipientEmail);
    form.append('subject', subject);
    form.append('html', html);
    for (const filePath of attachmentsFiles) {
      const name = path.basename(filePath);
      form.append('attachments', fs.createReadStream(filePath), { filename: name });
    }

    const headers = Object.assign({ Authorization: `Bearer ${AGENTSMAIL_API_KEY}` }, form.getHeaders());

    const res = await fetch(url, { method: 'POST', headers, body: form });
    const text = await res.text();
    if (!res.ok) {
      let body = text;
      try { body = JSON.parse(text); } catch (e) {}
      const err = new Error(`HTTP ${res.status}: ${JSON.stringify(body)}`);
      err.status = res.status;
      err.body = body;
      const retryAfter = res.headers && (res.headers.get && res.headers.get('retry-after'));
      if (retryAfter) err.retryAfter = Number(retryAfter);
      throw err;
    }
    try { return JSON.parse(text); } catch (e) { return { ok: true, raw: text }; }
  }

  // JSON send
  const payload = {
    mailbox: AGENTSMAIL_MAILBOX,
    mailbox_name: AGENTSMAIL_MAILBOX_NAME,
    to: recipientEmail,
    subject,
    html
  };

  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${AGENTSMAIL_API_KEY}` },
    body: JSON.stringify(payload)
  });

  const text = await res.text();
  if (!res.ok) {
    let body = text;
    try { body = JSON.parse(text); } catch (e) {}
    const err = new Error(`HTTP ${res.status}: ${JSON.stringify(body)}`);
    err.status = res.status;
    err.body = body;
    const retryAfter = res.headers && (res.headers.get && res.headers.get('retry-after'));
    if (retryAfter) err.retryAfter = Number(retryAfter);
    throw err;
  }
  try { return JSON.parse(text); } catch (e) { return { ok: true, raw: text }; }
}

async function sendWithRetries(email, subjectTmpl, htmlTmpl, vars, attachmentsFiles) {
  let attempt = 0;
  let lastErr = null;
  const subject = renderTemplate(subjectTmpl, vars);
  const html = renderTemplate(htmlTmpl, vars);

  while (attempt < maxRetries) {
    attempt += 1;
    try {
      const result = await sendMail(email, subject, html, attachmentsFiles);
      return { success: true, result };
    } catch (err) {
      lastErr = err;
      if (err.status === 401) return { success: false, error: 'UNAUTHORIZED - check AGENTSMAIL_API_KEY' };
      if (err.status === 403 && err.body && err.body.code === 'TRIAL_QUOTA_EXCEEDED') return { success: false, error: 'TRIAL_QUOTA_EXCEEDED' };
      if (err.status === 429) {
        const wait = err.retryAfter ? (Number(err.retryAfter) * 1000) : (1000 * attempt);
        console.warn(`Rate limited when sending to ${email}. Waiting ${wait}ms (attempt ${attempt}/${maxRetries})`);
        await sleep(wait);
        continue;
      }
      if (err.status >= 500 || !err.status) {
        const wait = 1000 * Math.pow(2, attempt - 1);
        console.warn(`Transient error sending to ${email}: ${err.message}. Retrying in ${wait}ms (attempt ${attempt}/${maxRetries})`);
        await sleep(wait);
        continue;
      }
      return { success: false, error: String(err.message) };
    }
  }
  return { success: false, error: lastErr ? String(lastErr.message) : 'unknown' };
}

(async function main() {
  try {
    const attachmentsFiles = await collectAttachmentStreams();
    const { recipients, subject, html } = await loadFiles();

    if (recipients.length === 0) {
      console.error('No valid recipients found. Use --csv or --emails.');
      process.exit(1);
    }

    const alreadySent = resume ? await loadSentSet() : new Set();

    console.log(`Sending to ${recipients.length} recipients in batches of ${batchSize} (delay ${delayMs}ms between batches)...`);
    if (dryRun) console.log('DRY RUN: no requests will be sent.');

    let successes = 0;
    let failures = 0;

    for (let i = 0; i < recipients.length; i += batchSize) {
      const batch = recipients.slice(i, i + batchSize);

      for (const r of batch) {
        const email = String((r.email || '').trim());
        if (!isEmail(email)) continue;
        if (alreadySent.has(email)) {
          console.log(`Skipping ${email} (already sent according to log)`);
          continue;
        }

        const vars = { ...r };
        process.stdout.write(`Sending to ${email} ... `);
        const result = await sendWithRetries(email, subject, html, vars, attachmentsFiles);
        const entry = { timestamp: new Date().toISOString(), email, vars, status: result.success ? 'success' : 'failure', result: result.success ? result.result : undefined, error: result.success ? undefined : result.error };
        await appendLog(entry);

        if (result.success) {
          successes += 1;
          console.log('OK');
        } else {
          failures += 1;
          console.log('FAILED -', result.error);
          if (String(result.error).includes('TRIAL_QUOTA_EXCEEDED')) {
            console.error('Trial quota reached; stopping further sends.');
            i = recipients.length; // break outer loop
            break;
          }
        }
      }

      if (i + batchSize < recipients.length) await sleep(delayMs);
    }

    console.log('\nDone.');
    console.log('Successes:', successes);
    console.log('Failures:', failures);
    console.log('Log written to', logPath);
  } catch (err) {
    console.error('Fatal error:', err);
    process.exit(1);
  }
})();
