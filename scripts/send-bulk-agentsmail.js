#!/usr/bin/env node

const fs = require('fs').promises;
const path = require('path');

require('dotenv').config();

const fetch = globalThis.fetch;
if (typeof fetch !== 'function') {
  console.error('This script requires Node 18+ (global fetch).');
  process.exit(1);
}

const argv = require('minimist')(process.argv.slice(2));

const emailsPath = argv.emails || argv.e || 'emails.txt';
const subjectPath = argv.subject || argv.s || 'subject.txt';
const htmlPath = argv.html || argv.h || 'letter.html';
const batchSize = Number(process.env.BATCH_SIZE || argv.batch || 1);
let delayMs = Number(process.env.DELAY_MS || argv.delay || 1000); // milliseconds between batches
const maxRetries = Number(process.env.MAX_RETRIES || argv.retries || 5);
const dryRun = argv.dry || argv.dryrun || false;

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
// To avoid hitting rate limits, ensure delayMs between batches is at least batchSize * 1000 ms
const minDelayMs = batchSize * 1000;
if (delayMs < minDelayMs) {
  console.warn(`Adjusting delay to meet AgentsMail rate limits: batchSize=${batchSize} => delay >= ${minDelayMs}ms`);
  delayMs = minDelayMs;
}

function sleep(ms) {
  return new Promise((res) => setTimeout(res, ms));
}

function isEmail(s) {
  return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(String(s).trim());
}

async function loadFiles() {
  const [emailsRaw, subjectRaw, htmlRaw] = await Promise.all([
    fs.readFile(path.resolve(emailsPath), 'utf8'),
    fs.readFile(path.resolve(subjectPath), 'utf8'),
    fs.readFile(path.resolve(htmlPath), 'utf8')
  ]);

  const emails = emailsRaw
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l.length > 0 && isEmail(l));

  const subject = subjectRaw.split(/\r?\n/).find(Boolean) || '';
  const html = htmlRaw;

  return { emails, subject, html };
}

async function sendMail(recipient, subject, html) {
  const url = AGENTSMAIL_BASE_URL.replace(/\/$/, '') + AGENTSMAIL_SEND_ENDPOINT;

  const payload = {
    mailbox: AGENTSMAIL_MAILBOX,
    mailbox_name: AGENTSMAIL_MAILBOX_NAME,
    to: recipient,
    subject,
    html
  };

  if (dryRun) {
    return { ok: true, dryRun: true, payload };
  }

  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${AGENTSMAIL_API_KEY}`
    },
    body: JSON.stringify(payload)
  });

  const text = await res.text();

  if (!res.ok) {
    // Try to parse structured error
    let body = text;
    try { body = JSON.parse(text); } catch (e) { /* leave as text */ }
    const err = new Error(`HTTP ${res.status}: ${JSON.stringify(body)}`);
    err.status = res.status;
    err.body = body;
    // attach rate-limit info if present
    const retryAfter = res.headers && (res.headers.get && res.headers.get('retry-after'));
    if (retryAfter) err.retryAfter = Number(retryAfter);
    throw err;
  }

  try {
    return JSON.parse(text);
  } catch (e) {
    return { ok: true, raw: text };
  }
}

async function sendWithRetries(email, subject, html) {
  let attempt = 0;
  let lastErr = null;

  while (attempt < maxRetries) {
    attempt += 1;
    try {
      const result = await sendMail(email, subject, html);
      return { success: true, result };
    } catch (err) {
      lastErr = err;
      // Handle specific API errors
      if (err.status === 401) {
        return { success: false, error: 'UNAUTHORIZED - check AGENTSMAIL_API_KEY' };
      }
      if (err.status === 403 && err.body && err.body.code === 'TRIAL_QUOTA_EXCEEDED') {
        return { success: false, error: 'TRIAL_QUOTA_EXCEEDED - trial send limit reached' };
      }
      if (err.status === 429) {
        // Rate limited: respect Retry-After if provided, otherwise exponential backoff
        const wait = err.retryAfter ? (Number(err.retryAfter) * 1000) : (1000 * attempt);
        console.warn(`Rate limited when sending to ${email}. Waiting ${wait}ms (attempt ${attempt}/${maxRetries})`);
        await sleep(wait);
        continue;
      }

      // For other 5xx or transient errors, exponential backoff
      if (err.status >= 500 || !err.status) {
        const wait = 1000 * Math.pow(2, attempt - 1);
        console.warn(`Transient error sending to ${email}: ${err.message}. Retrying in ${wait}ms (attempt ${attempt}/${maxRetries})`);
        await sleep(wait);
        continue;
      }

      // Non-retryable error
      return { success: false, error: String(err.message) };
    }
  }

  return { success: false, error: lastErr ? String(lastErr.message) : 'unknown' };
}

(async function main() {
  try {
    const { emails, subject, html } = await loadFiles();

    if (emails.length === 0) {
      console.error('No valid emails found in', emailsPath);
      process.exit(1);
    }

    console.log(`Sending to ${emails.length} recipients in batches of ${batchSize} (delay ${delayMs}ms between batches)...`);
    if (dryRun) console.log('DRY RUN: no requests will be sent.');

    const successes = [];
    const failures = [];

    for (let i = 0; i < emails.length; i += batchSize) {
      const batch = emails.slice(i, i + batchSize);

      // Send sequentially within the batch to be safe with rate limits
      for (const email of batch) {
        process.stdout.write(`Sending to ${email} ... `);
        const res = await sendWithRetries(email, subject, html);
        if (res.success) {
          successes.push({ email, res: res.result });
          console.log('OK');
        } else {
          failures.push({ email, error: res.error });
          console.log('FAILED -', res.error);
          // If trial quota exceeded, abort further sends
          if (String(res.error).includes('TRIAL_QUOTA_EXCEEDED')) {
            console.error('Trial quota reached; stopping further sends.');
            i = emails.length; // break outer loop
            break;
          }
        }
      }

      if (i + batchSize < emails.length) await sleep(delayMs);
    }

    console.log('\nDone.');
    console.log('Successes:', successes.length);
    console.log('Failures:', failures.length);

    if (failures.length > 0) {
      console.log('\nFailed deliveries:');
      for (const f of failures) console.log(`${f.email} => ${f.error}`);
    }
  } catch (err) {
    console.error('Fatal error:', err);
    process.exit(1);
  }
})();
