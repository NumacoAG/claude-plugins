#!/usr/bin/env node
/* Render a Paged.js document to PDF by driving the system Chrome via puppeteer-core.
   This is the reliable path: it waits for Paged.js to finish pagination (our
   data-paged-done sentinel, set by PagedConfig.after) before printing, which the
   plain `chrome --print-to-pdf` CLI cannot guarantee.
   Usage: node render_paged.js <htmlAbsPath> <pdfAbsPath> <chromeExecPath> [budgetMs] */
const puppeteer = require('puppeteer-core');

(async () => {
  const htmlPath = process.argv[2];
  const pdfPath = process.argv[3];
  const chromePath = process.argv[4];
  const budget = parseInt(process.argv[5] || '90000', 10);
  if (!htmlPath || !pdfPath || !chromePath) {
    console.error('usage: node render_paged.js <html> <pdf> <chrome> [budgetMs]');
    process.exit(2);
  }
  const browser = await puppeteer.launch({
    executablePath: chromePath,
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu', '--no-first-run'],
  });
  try {
    const page = await browser.newPage();
    await page.goto('file://' + htmlPath, { waitUntil: 'networkidle0', timeout: budget });
    try {
      await page.waitForFunction(
        () => document.documentElement.getAttribute('data-paged-done') === '1',
        { timeout: budget }
      );
    } catch (e) {
      console.error('warn: Paged.js completion sentinel not seen within budget; printing current state');
    }
    // count paginated pages for the caller's sanity check
    const n = await page.evaluate(() => document.querySelectorAll('.pagedjs_page').length);
    console.error('pagedjs pages: ' + n);
    await page.pdf({ path: pdfPath, printBackground: true, preferCSSPageSize: true, margin: { top: 0, right: 0, bottom: 0, left: 0 } });
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error(e && e.stack ? e.stack : String(e)); process.exit(1); });
