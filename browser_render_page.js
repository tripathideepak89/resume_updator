#!/usr/bin/env node
/*
 * Render a JavaScript-heavy job page and return title/body text as JSON.
 */

const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

function pickChromePath() {
  const candidates = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
  ];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate;
  }
  return undefined;
}

async function main() {
  const url = process.argv[2];
  if (!url) {
    throw new Error("Usage: node browser_render_page.js <url>");
  }

  const executablePath = pickChromePath();
  const browser = await chromium.launch({
    headless: true,
    executablePath,
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1400 } });
  await page.goto(url, { waitUntil: "networkidle", timeout: 60000 });
  await page.waitForTimeout(2500);

  const result = {
    url: page.url(),
    title: await page.title(),
    text: await page.locator("body").innerText(),
  };
  console.log(JSON.stringify(result, null, 2));
  await browser.close();
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
