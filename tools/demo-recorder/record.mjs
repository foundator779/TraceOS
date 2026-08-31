import { chromium } from "playwright";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../..");
const outputDir = path.join(root, "docs", "submission_evidence", "video");
const smokeMode = process.argv.includes("--smoke");
const finalPath = path.join(outputDir, smokeMode ? "TraceOS_cursor_smoke.webm" : "TraceOS_continuous_demo_source.webm");
const liveUrl = "https://traceos-1060372410958.us-central1.run.app";
const chromePath = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";

await fs.mkdir(outputDir, { recursive: true });

const browser = await chromium.launch({
  executablePath: chromePath,
  headless: true,
  args: ["--disable-gpu", "--hide-scrollbars", "--autoplay-policy=no-user-gesture-required"],
});

const context = await browser.newContext({
  viewport: { width: 2304, height: 1296 },
  screen: { width: 2304, height: 1296 },
  deviceScaleFactor: 1,
  colorScheme: "dark",
  reducedMotion: "no-preference",
  recordVideo: {
    dir: outputDir,
    size: { width: 2304, height: 1296 },
  },
});

const page = await context.newPage();
const video = page.video();

const pause = (ms) => page.waitForTimeout(smokeMode ? Math.max(250, Math.round(ms * 0.12)) : ms);
const moveTo = async (target, xRatio = 0.5, yRatio = 0.5) => {
  await target.scrollIntoViewIfNeeded();
  const box = await target.boundingBox();
  if (!box) throw new Error("Demo target is not visible");
  await page.mouse.move(box.x + box.width * xRatio, box.y + box.height * yRatio, { steps: 30 });
  await pause(300);
  return box;
};
const humanClick = async (target, wait = 4000, xRatio = 0.5, yRatio = 0.5) => {
  const box = await moveTo(target, xRatio, yRatio);
  const x = box.x + box.width * xRatio;
  const y = box.y + box.height * yRatio;
  await page.mouse.down();
  await pause(120);
  await page.mouse.up();
  await page.mouse.move(x + 12, y + 5, { steps: 7 });
  await pause(wait);
};
const clickText = async (name, wait = 5000) => {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const target = page.getByRole("button", { name: new RegExp(`^${escaped}(?:\\s|$)`, "i") }).first();
  await humanClick(target, wait);
};
const top = async () => page.evaluate(() => window.scrollTo({ top: 0, behavior: "smooth" }));
const scrollTo = async (fraction) => {
  await page.evaluate(value => window.scrollTo({ top: document.body.scrollHeight * value, behavior: "smooth" }), fraction);
  await pause(2200);
};

try {
  await page.goto(liveUrl, { waitUntil: "networkidle", timeout: 120000 });
  await page.addStyleTag({ content: `
    * { cursor: none !important; }
    html { scroll-behavior: smooth !important; }
    .recording-cursor {
      position: fixed; z-index: 1000001; left: 48px; top: 48px; width: 25px; height: 25px;
      border: 2px solid #fff; border-radius: 50%; pointer-events: none;
      transform: translate(-50%,-50%); box-shadow: 0 2px 12px rgba(0,0,0,.6), inset 0 0 0 3px rgba(17,16,15,.42);
      transition: width .12s ease, height .12s ease, background .12s ease;
    }
    .recording-cursor::after { position:absolute; left:50%; top:50%; width:5px; height:5px; content:""; border-radius:50%; background:#d7d1b0; transform:translate(-50%,-50%); }
    .recording-cursor.clicking { width: 38px; height: 38px; background: rgba(215,209,176,.2); }
  ` });
  await page.evaluate(() => {
    const cursor = document.createElement("div");
    cursor.className = "recording-cursor";
    document.body.appendChild(cursor);
    document.addEventListener("mousemove", event => {
      cursor.style.left = `${event.clientX}px`;
      cursor.style.top = `${event.clientY}px`;
    });
    document.addEventListener("mousedown", () => cursor.classList.add("clicking"));
    document.addEventListener("mouseup", () => setTimeout(() => cursor.classList.remove("clicking"), 130));
  });

  await page.mouse.move(80, 90, { steps: 10 });
  await pause(5000);
  await clickText("Run evidence replay", 10000);

  // Follow the image path, rejected claim, and verified result through obvious focus controls.
  await top();
  await pause(5000);
  await humanClick(page.getByRole("button", { name: "Stopped claim", exact: true }), 5500);
  await humanClick(page.getByRole("button", { name: "Verified finding", exact: true }), 5500);
  await humanClick(page.getByRole("button", { name: "Image path", exact: true }), 3500);

  // Show distinct identities, tools, and scopes.
  await clickText("Fleet", 5500);
  await scrollTo(0.45);
  await pause(4500);
  await top();
  await pause(1500);

  // Return to the active case and show governance failure/recovery.
  await clickText("Cases", 4000);
  const caseRow = page.getByRole("button", { name: /CASE-042/i }).first();
  await humanClick(caseRow, 4500);
  await clickText("Overview", 4500);
  await scrollTo(0.52);
  await pause(5500);

  await clickText("Hypotheses", 5000);
  await clickText("Memory", 5000);
  await clickText("Report", 6500);

  // Show independent Gemma challenge, media operations, hashes, and cost boundary.
  await clickText("Training", 6000);
  await scrollTo(0.35);
  await pause(5000);
  const trainingVideo = page.locator("video").first();
  if (await trainingVideo.count()) {
    await humanClick(trainingVideo, 6500, 0.5, 0.55);
  }
  await scrollTo(1);
  await pause(5000);

  // Live enterprise source and observability proof.
  await clickText("Integrations", 6000);
  await scrollTo(0.48);
  await pause(5000);
  await clickText("Observability", 6000);
  await scrollTo(0.42);
  await pause(5000);

  // End on the architecture at full resolution within the same continuous take.
  const architecture = await fs.readFile(path.join(root, "docs", "architecture.svg"), "utf8");
  await page.setContent(`<html><head><style>html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#11100f}svg{display:block;width:100vw;height:100vh}</style></head><body>${architecture}</body></html>`, { waitUntil: "load" });
  await pause(10000);
} finally {
  await page.close();
  await context.close();
  await browser.close();
}

const recordedPath = await video.path();
await fs.rm(finalPath, { force: true });
await fs.rename(recordedPath, finalPath);
console.log(finalPath);
