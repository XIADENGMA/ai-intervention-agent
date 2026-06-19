#!/usr/bin/env node
/**
 * Summarize VS Code Webview retainContextWhenHidden restore probes.
 *
 * How to capture:
 *
 *   AIIA_WEBVIEW_BENCH_OUTPUT=/tmp/aiia-webview-retain.ndjson code .
 *
 * Then open the AI Intervention Agent view, hide/show the sidebar a few times,
 * and summarize:
 *
 *   node scripts/bench_vscode_webview_retain.mjs \
 *     --input /tmp/aiia-webview-retain.ndjson
 *
 * The extension writes one NDJSON row per visible restore probe. Rows include
 * host round-trip time, webview two-rAF paint latency, and Chromium heap fields
 * when `performance.memory` is available.
 */

import fs from "node:fs";

function usage() {
  return [
    "Usage: node scripts/bench_vscode_webview_retain.mjs --input <file|-> [--json]",
    "",
    "Capture with:",
    "  AIIA_WEBVIEW_BENCH_OUTPUT=/tmp/aiia-webview-retain.ndjson code .",
    "",
    "Then hide/show the AI Intervention Agent view and summarize the NDJSON file.",
  ].join("\n");
}

function parseArgs(argv) {
  const args = { input: "", json: false };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--input" || arg === "-i") {
      args.input = argv[i + 1] || "";
      i += 1;
    } else if (arg === "--json") {
      args.json = true;
    } else if (arg === "--help" || arg === "-h") {
      args.help = true;
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }
  return args;
}

function percentile(sorted, p) {
  if (!sorted.length) return null;
  if (sorted.length === 1) return sorted[0];
  const idx = Math.ceil((p / 100) * sorted.length) - 1;
  return sorted[Math.max(0, Math.min(sorted.length - 1, idx))];
}

function summarizeSeries(values) {
  const nums = values
    .filter((v) => typeof v === "number" && Number.isFinite(v))
    .sort((a, b) => a - b);
  if (!nums.length) {
    return { count: 0, min: null, p50: null, p95: null, max: null };
  }
  return {
    count: nums.length,
    min: nums[0],
    p50: percentile(nums, 50),
    p95: percentile(nums, 95),
    max: nums[nums.length - 1],
  };
}

function parseRows(text) {
  const rows = [];
  for (const [idx, line] of text.split(/\r?\n/).entries()) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      const row = JSON.parse(trimmed);
      if (row && typeof row === "object") rows.push(row);
    } catch (error) {
      throw new Error(`Invalid JSON on line ${idx + 1}: ${error.message}`);
    }
  }
  return rows;
}

function summarizeRows(rows) {
  const usedHeap = rows
    .map((r) => r.usedJSHeapSize)
    .filter((v) => typeof v === "number" && Number.isFinite(v));
  return {
    samples: rows.length,
    retainContextWhenHidden: rows.some((r) => r.retainContextWhenHidden === true),
    roundTripMs: summarizeSeries(rows.map((r) => r.roundTripMs)),
    paintLatencyMs: summarizeSeries(rows.map((r) => r.paintLatencyMs)),
    usedJSHeapSize: summarizeSeries(usedHeap),
    usedJSHeapDelta:
      usedHeap.length >= 2 ? usedHeap[usedHeap.length - 1] - usedHeap[0] : null,
  };
}

function formatNumber(value, suffix = "") {
  if (typeof value !== "number" || !Number.isFinite(value)) return "n/a";
  return `${value.toFixed(2)}${suffix}`;
}

function bytesToMb(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return value / 1024 / 1024;
}

function printHuman(summary) {
  console.log(`samples: ${summary.samples}`);
  console.log(`retainContextWhenHidden: ${summary.retainContextWhenHidden}`);
  for (const [label, stats] of [
    ["roundTripMs", summary.roundTripMs],
    ["paintLatencyMs", summary.paintLatencyMs],
  ]) {
    console.log(
      `${label}: p50=${formatNumber(stats.p50, "ms")} p95=${formatNumber(
        stats.p95,
        "ms",
      )} max=${formatNumber(stats.max, "ms")} count=${stats.count}`,
    );
  }
  const heap = summary.usedJSHeapSize;
  console.log(
    `usedJSHeapSize: p50=${formatNumber(bytesToMb(heap.p50), "MB")} ` +
      `p95=${formatNumber(bytesToMb(heap.p95), "MB")} count=${heap.count}`,
  );
  const deltaMb =
    typeof summary.usedJSHeapDelta === "number"
      ? bytesToMb(summary.usedJSHeapDelta)
      : null;
  console.log(`usedJSHeapDelta: ${formatNumber(deltaMb, "MB")}`);
}

function readInput(input) {
  if (input === "-") return fs.readFileSync(0, "utf8");
  return fs.readFileSync(input, "utf8");
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help || !args.input) {
    console.log(usage());
    return;
  }
  const rows = parseRows(readInput(args.input));
  const summary = summarizeRows(rows);
  if (args.json) {
    console.log(JSON.stringify(summary, null, 2));
  } else {
    printHuman(summary);
  }
}

try {
  main();
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
}
