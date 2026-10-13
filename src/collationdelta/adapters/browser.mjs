#!/usr/bin/env node
// Chromium only. The core supervisor owns the adapter and browser process group.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { parseArgs } from 'node:util';
import { setTimeout as delay } from 'node:timers/promises';
import { observeIntl } from './intl.mjs';

let child, browser, context, directory, timer;
let deadlineFailure;
const failed = new Promise((_, reject) => { deadlineFailure = reject; });
const bounded = promise => Promise.race([promise, failed]);
const credentialStoreFlags = ['--password-store=basic', '--use-mock-keychain'];

// SIGKILL cleanup belongs to the outer process group supervisor.
for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
  process.on(signal, () => {
    deadlineFailure(new Error(`adapter interrupted: ${signal}`));
  });
}

async function cleanup() {
  // An unresponsive browser must not hold failure cleanup indefinitely.
  if (child && child.exitCode === null && child.signalCode === null) {
    child.kill('SIGTERM');
    await Promise.race([
      new Promise(resolve => child.once('exit', resolve)),
      delay(1000, undefined, { ref: false }),
    ]);
    if (child.exitCode === null && child.signalCode === null) {
      child.kill('SIGKILL');
      await Promise.race([
        new Promise(resolve => child.once('exit', resolve)),
        delay(1000, undefined, { ref: false }),
      ]);
    }
    if (child.exitCode === null && child.signalCode === null) {
      throw new Error('browser process did not exit during cleanup');
    }
  }
  // A descendant may retain diagnostic pipes after the browser exits.
  child?.stdout?.destroy();
  child?.stderr?.destroy();
  if (browser) {
    await Promise.race([browser.close(), delay(1000, undefined, { ref: false })]);
  }
  if (directory) {
    await fs.promises.rm(directory, {
      recursive: true,
      force: true,
      maxRetries: 5,
      retryDelay: 50,
    });
  }
}

async function main() {
  if (!['darwin', 'linux'].includes(process.platform)) {
    throw new Error('browser adapter requires Linux or macOS');
  }
  const { values } = parseArgs({
    options: {
      executable: { type: 'string' },
      toolchain: { type: 'string' },
      'deadline-ms': { type: 'string', default: '20000' },
      'distribution-label': { type: 'string' },
    },
  });
  for (const name of ['executable', 'toolchain']) {
    if (!values[name] || !path.isAbsolute(values[name])) {
      throw new Error(`--${name} must be an explicit absolute path`);
    }
  }
  const deadline = Number(values['deadline-ms']);
  if (!Number.isSafeInteger(deadline) || deadline <= 0 || deadline > 2147483647) {
    throw new Error('--deadline-ms must be a positive integer <= 2147483647');
  }
  timer = setTimeout(() => {
    deadlineFailure(new Error(`browser adapter deadline after ${deadline}ms`));
  }, deadline);

  const require = createRequire(import.meta.url);
  const packageRoot = path.join(values.toolchain, 'node_modules', 'playwright-core');
  const packageFile = path.join(packageRoot, 'package.json');
  if (!fs.existsSync(packageFile)) {
    throw new Error(`toolchain must contain an installed playwright-core package: ${packageRoot}`);
  }
  const { chromium } = require(packageRoot);
  const automationVersion = require(packageFile).version;
  fs.accessSync(values.executable, fs.constants.X_OK);

  const readRequest = async () => {
    const chunks = [];
    let bytes = 0;
    for await (const chunk of process.stdin) {
      bytes += chunk.length;
      if (bytes > 32 * 1024 * 1024) {
        throw new Error('browser adapter stdin exceeds 32 MiB');
      }
      chunks.push(chunk);
    }
    const text = new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks));
    return JSON.parse(text);
  };
  const request = await bounded(readRequest());
  directory = fs.mkdtempSync(path.join(os.tmpdir(), 'collationdelta-browser-'));
  child = spawn(values.executable, [
    '--headless',
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-background-networking',
    '--disable-component-update',
    '--disable-sync',
    '--disable-crashpad-for-testing',
    ...credentialStoreFlags,
    '--remote-debugging-address=127.0.0.1',
    '--remote-debugging-port=0',
    `--user-data-dir=${directory}`,
    'about:blank',
  ], { detached: false, stdio: ['ignore', 'pipe', 'pipe'] });
  child.on('error', error => deadlineFailure(error));
  // Browser logs are diagnostics, never protocol output.
  child.stdout.on('data', chunk => process.stderr.write(chunk));
  child.stderr.on('data', chunk => process.stderr.write(chunk));

  const endpoint = await bounded((async () => {
    while (true) {
      if (child.exitCode !== null || child.signalCode !== null) {
        throw new Error(
          `browser exited before CDP became available (code=${child.exitCode}, signal=${child.signalCode})`,
        );
      }
      try {
        const portFile = fs.readFileSync(path.join(directory, 'DevToolsActivePort'), 'utf8');
        const [port, suffix] = portFile.trim().split('\n');
        // Chromium creates the file before writing its endpoint.
        if (port && suffix) {
          if (!/^\d+$/.test(port) || !suffix.startsWith('/devtools/browser/')) {
            throw new Error('invalid local CDP endpoint');
          }
          return `ws://127.0.0.1:${port}${suffix}`;
        }
      } catch (error) {
        if (error.code !== 'ENOENT') throw error;
      }
      await delay(25);
    }
  })());
  browser = await bounded(chromium.connectOverCDP(endpoint, { timeout: deadline }));
  context = await bounded(browser.newContext());
  await bounded(context.route('**/*', route => route.abort()));
  const page = await bounded(context.newPage());
  // Static source is serialized; corpus/profile are structured arguments.
  const response = await bounded(page.evaluate(observeIntl, request));
  const environment = await bounded(page.evaluate(() => ({
    user_agent: navigator.userAgent,
    navigator_platform: navigator.platform,
    execution_context: {
      url: location.href,
      has_document: typeof document === 'object',
      has_process: typeof process !== 'undefined',
    },
  })));
  response.runtime = {
    ...response.runtime,
    browser: { engine: 'chromium', version: browser.version(), ...environment },
    automation: { name: 'playwright-core', version: automationVersion },
    host: {
      node: process.version,
      platform: process.platform,
      arch: process.arch,
      release: os.release(),
    },
    selection: {
      executable: fs.realpathSync(values.executable),
      caller_labels: values['distribution-label']
        ? { distribution: values['distribution-label'] }
        : {},
    },
    execution: {
      mode: 'headless',
      transport: 'local-cdp',
      disposable_context: true,
      credential_store_flags: credentialStoreFlags,
    },
  };
  response.adapter = {
    name: 'collationdelta-browser-intl',
    version: '0.2.0',
    contract: 'intl.collator.v1',
  };

  await bounded(context.close());
  const cdp = await bounded(browser.newBrowserCDPSession());
  // Disconnecting CDP alone does not promise to shut down Chromium.
  await bounded(cdp.send('Browser.close'));
  if (child.exitCode === null && child.signalCode === null) {
    await bounded(Promise.race([
      new Promise(resolve => child.once('exit', resolve)),
      delay(1000, undefined, { ref: false }),
    ]));
  }
  await bounded(cleanup());
  process.stdout.write(JSON.stringify(response) + '\n');
}

try {
  await main();
} catch (error) {
  process.stderr.write(`adapter error: ${error.message}\n`);
  process.exitCode = 1;
} finally {
  clearTimeout(timer);
  try {
    await cleanup();
  } catch (error) {
    process.stderr.write(`adapter cleanup error: ${error.message}\n`);
    process.exitCode = 1;
  }
  // Cancel a pending stdin read after a deadline or transport error.
  process.stdin.destroy();
}
