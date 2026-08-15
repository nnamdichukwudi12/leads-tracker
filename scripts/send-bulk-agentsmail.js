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
const batchSize = Number(process.env.BATCH_SIZE || argv.batch || 10);
const delayMs = Number(process.env.DELAY_MS || argv.delay || 500);
const maxRetries = Number(process.env.MAX_RETRIES || 3);

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

function sleep(ms) {
  return new Promise((res) => setTimeout(res, ms));
}

function isEmail(s) {
  // basic email validation
  return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(s.trim());
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

  const subject = subjectRaw.split(/\r?\n/)[0].trim();
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

  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${AGENTSMAIL_API_KEY}`
    },
    body: JSON.stringify(payload),
    // timeout and other options can be added if needed
  });

  const text = await res.text();
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${text}`);
  }

  try {
    return JSON.parse(text);
  } catch (e) {
    return { ok: true, raw: text };
  }
}

async function sendWithRetries(email, subject, html) {
  let attempt = 0;
  while (attempt < maxRetries) {
    try {
      const result = await sendMail(email, subject, html);
      return { success: true, result };
    } catch (err) {
      attempt += 1;
      if (attempt >= maxRetries) {
        return { success: false, error: err.message };
      }
      await sleep(1000 * attempt); // exponential-ish backoff
    }
  }
}

(async function main() {
  try {
    const { emails, subject, html } = await loadFiles();

    if (emails.length === 0) {
      console.error('No valid emails found in', emailsPath);
      process.exit(1);
    }

    console.log(`Sending to ${emails.length} recipients in batches of ${batchSize} (delay ${delayMs}ms between batches)...`);

    const successes = [];
    const failures = [];

    for (let i = 0; i < emails.length; i += batchSize) {
      const batch = emails.slice(i, i + batchSize);

      const promises = batch.map((email) => sendWithRetries(email, subject, html).then((r) => ({ email, ...r })));

      const results = await Promise.all(promises);

      for (const r of results) {
        if (r.success) successes.push(r);
        else failures.push(r);
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
