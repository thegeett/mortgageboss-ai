#!/usr/bin/env node
// Screenshot one Stage 3 screen the way the reference PNGs were drawn (LP-934). Dev only.
//
//   node scripts/visual-check/shoot.mjs <S3-xx> <out.png> <height> '<seed JSON>'
//
// `run.sh` is the usual way in. The seed JSON is `seed.py`'s one line: the path to open, the moment to
// freeze the page's clock at, the clicks that open the screen, and the seeded processor's login.
//
// NO DEPENDENCY. Node's built-in `WebSocket` and `fetch` drive headless Chrome over the DevTools
// protocol, as LP-909 §5 did; no Playwright, no Puppeteer, nothing from npm. Chrome is found at
// $CHROME, else the usual macOS and Linux paths.
//
// What it fixes, so two runs of one state give the same picture: 1600 px wide and the reference PNG's
// own height, device scale 1, the light theme, en-US, America/New_York, and a clock that starts at the
// state's moment and runs forward from there (a frozen `Date.now` would stop timers the page relies on).

import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [, , screen, outFile, heightArg, seedJson] = process.argv;
if (!screen || !outFile || !heightArg || !seedJson) {
  console.error("usage: shoot.mjs <S3-xx> <out.png> <height> '<seed JSON>'");
  process.exit(2);
}
const WIDTH = 1600;
const HEIGHT = Number(heightArg);
const FRONTEND = process.env.VISUAL_FRONTEND ?? "http://localhost:3011";
const API = process.env.VISUAL_API ?? "http://localhost:8011";
const seed = JSON.parse(seedJson);

function chromePath() {
  const candidates = [
    process.env.CHROME,
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
  ].filter(Boolean);
  const found = candidates.find((path) => existsSync(path));
  if (!found) throw new Error(`no Chrome found; set CHROME (tried ${candidates.join(", ")})`);
  return found;
}

function launch() {
  const profile = mkdtempSync(join(tmpdir(), "visual-check-"));
  const child = spawn(
    chromePath(),
    [
      "--headless=new",
      "--remote-debugging-port=0",
      `--user-data-dir=${profile}`,
      `--window-size=${WIDTH},${HEIGHT}`,
      "--hide-scrollbars",
      "--force-device-scale-factor=1",
      "--no-first-run",
      "--no-default-browser-check",
      "--disable-extensions",
      "--lang=en-US",
      "about:blank",
    ],
    { stdio: ["ignore", "ignore", "pipe"] },
  );
  const endpoint = new Promise((resolve, reject) => {
    let buffer = "";
    child.stderr.on("data", (chunk) => {
      buffer += chunk;
      const match = buffer.match(/DevTools listening on (ws:\/\/\S+)/);
      if (match) resolve(match[1]);
    });
    child.on("exit", (code) => reject(new Error(`Chrome exited early (${code})`)));
    setTimeout(() => reject(new Error("Chrome did not start within 20 s")), 20_000);
  });
  const close = async () => {
    const exited = new Promise((resolve) => child.once("exit", resolve));
    child.kill("SIGTERM");
    await Promise.race([exited, sleep(5000)]);
    rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  };
  return { endpoint, close };
}

/** One DevTools connection; `send` targets the attached page session once there is one. */
function connect(url) {
  const socket = new WebSocket(url);
  let nextId = 1;
  const pending = new Map();
  const listeners = [];
  socket.onmessage = (message) => {
    const data = JSON.parse(message.data);
    if (data.id && pending.has(data.id)) {
      const { resolve, reject } = pending.get(data.id);
      pending.delete(data.id);
      if (data.error) reject(new Error(`${data.error.message} (${data.error.code})`));
      else resolve(data.result);
    } else if (data.method) {
      for (const listener of listeners) listener(data);
    }
  };
  const opened = new Promise((resolve, reject) => {
    socket.onopen = resolve;
    socket.onerror = reject;
  });
  const call = (method, params, sessionId) =>
    new Promise((resolve, reject) => {
      const id = nextId++;
      pending.set(id, { resolve, reject });
      socket.send(
        JSON.stringify({ id, method, params: params ?? {}, ...(sessionId ? { sessionId } : {}) }),
      );
    });
  const waitFor = (method, timeoutMs = 30_000) =>
    new Promise((resolve, reject) => {
      const timer = setTimeout(
        () => reject(new Error(`timed out waiting for ${method}`)),
        timeoutMs,
      );
      listeners.push(function once(event) {
        if (event.method === method) {
          clearTimeout(timer);
          listeners.splice(listeners.indexOf(once), 1);
          resolve(event);
        }
      });
    });
  const on = (listener) => listeners.push(listener);
  return { opened, call, waitFor, on, close: () => socket.close() };
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** A `Date` that starts at `iso` and runs forward: the page reads the state's moment, timers still tick. */
function clockScript(iso) {
  return `(() => {
    const RealDate = Date;
    const offset = new RealDate(${JSON.stringify(iso)}).getTime() - RealDate.now();
    class FrozenDate extends RealDate {
      constructor(...args) { args.length === 0 ? super(RealDate.now() + offset) : super(...args); }
      static now() { return RealDate.now() + offset; }
    }
    globalThis.Date = FrozenDate;
  })();`;
}

async function main() {
  const chrome = launch();
  try {
    const browser = connect(await chrome.endpoint);
    await browser.opened;
    const { targetId } = await browser.call("Target.createTarget", { url: "about:blank" });
    const { sessionId } = await browser.call("Target.attachToTarget", { targetId, flatten: true });
    const page = (method, params) => browser.call(method, params, sessionId);

    await page("Page.enable");
    await page("Runtime.enable");
    await page("Network.enable");
    await page("Emulation.setDeviceMetricsOverride", {
      width: WIDTH,
      height: HEIGHT,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await page("Emulation.setEmulatedMedia", {
      features: [{ name: "prefers-color-scheme", value: "light" }],
    });
    await page("Emulation.setTimezoneOverride", { timezoneId: "America/New_York" });
    await page("Emulation.setLocaleOverride", { locale: "en-US" });
    await page("Page.addScriptToEvaluateOnNewDocument", { source: clockScript(seed.now) });
    // `next dev`'s overlay and the TanStack Query devtools button are not the app; hide them, but REPORT every page error
    // below, so hiding the badge never hides the problem it was pointing at.
    await page("Page.addScriptToEvaluateOnNewDocument", {
      source: `document.addEventListener("DOMContentLoaded", () => {
        const style = document.createElement("style");
        style.textContent = "nextjs-portal, .tsqd-open-btn-container { display: none !important; }";
        document.head.appendChild(style);
      });`,
    });
    const pageErrors = [];
    const requests = new Map();
    browser.on((event) => {
      if (event.method === "Runtime.exceptionThrown") {
        pageErrors.push(event.params.exceptionDetails?.exception?.description ?? "exception");
      } else if (event.method === "Network.loadingFailed" && !event.params.canceled) {
        pageErrors.push(
          `request failed (${event.params.errorText}): ${requests.get(event.params.requestId) ?? "?"}`,
        );
      } else if (event.method === "Network.requestWillBeSent") {
        requests.set(
          event.params.requestId,
          `${event.params.request.method} ${event.params.request.url}`,
        );
      } else if (event.method === "Runtime.consoleAPICalled" && event.params.type === "error") {
        pageErrors.push(event.params.args.map((a) => a.value ?? a.description ?? "").join(" "));
      }
    });

    const go = async (url) => {
      const loaded = browser.waitFor("Page.loadEventFired");
      await page("Page.navigate", { url });
      await loaded;
    };
    const evaluate = async (expression) => {
      const { result, exceptionDetails } = await page("Runtime.evaluate", {
        expression,
        awaitPromise: true,
        returnByValue: true,
      });
      if (exceptionDetails)
        throw new Error(exceptionDetails.exception?.description ?? "evaluate failed");
      return result.value;
    };

    // Sign in through the real endpoint, from the frontend's origin, so the refresh cookie lands
    // where the app's silent refresh will look for it.
    await go(`${FRONTEND}/login`);
    const status = await evaluate(
      `fetch(${JSON.stringify(`${API}/api/v1/auth/login`)}, {
         method: "POST", credentials: "include",
         headers: { "Content-Type": "application/json" },
         body: JSON.stringify({ email: ${JSON.stringify(seed.email)}, password: ${JSON.stringify(seed.password)} }),
       }).then((r) => r.status)`,
    );
    if (status !== 200) throw new Error(`login returned ${status}`);

    await go(`${FRONTEND}${seed.path}`);
    await sleep(3000); // silent refresh, then the page's queries

    for (const text of seed.clicks ?? []) {
      const clicked = await evaluate(`(() => {
        const want = ${JSON.stringify(text)};
        const all = [...document.querySelectorAll("button, a, [role=button], [role=row], tr, td, span, div")];
        // The INNERMOST element that reads exactly the text: a table cell holding a button reads the
        // same text as the button, and clicking the cell clicks nothing.
        const hit = all.find(
          (el) =>
            el.offsetParent !== null &&
            el.textContent.trim() === want &&
            ![...el.children].some((child) => child.textContent.trim() === want),
        );
        if (!hit) return false;
        hit.click();
        return true;
      })()`);
      if (!clicked) throw new Error(`nothing visible reads exactly ${JSON.stringify(text)}`);
      await sleep(1500);
    }
    await sleep(500);
    // A dialog or sheet focuses its first control on open; the reference screens show no focus ring.
    await evaluate("document.activeElement instanceof HTMLElement && document.activeElement.blur()");
    await sleep(200);
    if (process.env.VISUAL_DEBUG) {
      const fixed = await evaluate(`[...document.querySelectorAll("body *")]
        .filter((el) => getComputedStyle(el).position === "fixed" && el.getBoundingClientRect().width > 0)
        .map((el) => el.tagName.toLowerCase() + (el.id ? "#" + el.id : "") + "." + (el.className?.toString?.() ?? "").slice(0, 80))`);
      console.error(`${screen}: fixed elements: ${JSON.stringify(fixed)}`);
    }

    const { data } = await page("Page.captureScreenshot", {
      format: "png",
      clip: { x: 0, y: 0, width: WIDTH, height: HEIGHT, scale: 1 },
    });
    writeFileSync(outFile, Buffer.from(data, "base64"));
    for (const error of pageErrors) console.error(`${screen}: page error: ${error.slice(0, 300)}`);
    console.log(`${screen}: saved ${outFile} (${WIDTH}x${HEIGHT}, now ${seed.now})`);
    browser.close();
  } finally {
    await chrome.close();
  }
}

main().catch((error) => {
  console.error(`${screen}: ${error.message}`);
  process.exit(1);
});
