#!/usr/bin/env node

import fs from "fs";

const args = process.argv.slice(2);
const jsonMode = args[0] === "--json";
const filePath = jsonMode ? args[1] : args[0];
if (!filePath) {
  process.exit(1);
}

let content = "";
try {
  content = fs.readFileSync(filePath, "utf8");
} catch {
  process.exit(0);
}

let latestUsage = null;
let latestRateLimits = [];
const limitSnapshots = new Map();

for (const rawLine of content.split(/\r?\n/)) {
  const line = rawLine.trim();
  if (!line) {
    continue;
  }

  const inlineUsage = parseTokenUsageLine(line);
  if (inlineUsage) {
    latestUsage = inlineUsage;
    continue;
  }

  let parsed;
  try {
    parsed = JSON.parse(line);
  } catch {
    continue;
  }

  walk(parsed, (obj) => {
    const usage = extractUsage(obj);
    if (usage) {
      latestUsage = usage;
    }

    const limits = extractRateLimits(obj);
    if (limits.length > 0) {
      latestRateLimits = limits;
      for (const limit of selectPreferredLimits(limits)) {
        const current = limitSnapshots.get(limit.label);
        if (!current) {
          limitSnapshots.set(limit.label, { start: limit.used, end: limit.used });
        } else {
          current.end = limit.used;
        }
      }
    }
  });
}

const parts = [];

if (latestUsage) {
  const usageBits = [];
  if (latestUsage.input != null) {
    usageBits.push(`${formatNumber(latestUsage.input)} in`);
  }
  if (latestUsage.output != null) {
    usageBits.push(`${formatNumber(latestUsage.output)} out`);
  }
  if (latestUsage.cached != null && Number(latestUsage.cached) > 0) {
    usageBits.push(`${formatNumber(latestUsage.cached)} cached`);
  }

  // Text output shows the corrected effective (matches --json output and
  // coord-tokens.sh). Previously this path printed raw total_tokens which
  // mis-represented spend by counting cache_read at the full input rate.
  const effective = computeCodexEffective(latestUsage);
  if (effective != null) {
    let tokenText = `tokens ${formatNumber(effective)} effective`;
    if (usageBits.length > 0) {
      tokenText += ` (${usageBits.join(", ")})`;
    }
    parts.push(tokenText);
  }
}

if (latestRateLimits.length > 0) {
  const limitsText = selectPreferredLimits(latestRateLimits)
    .map((limit) => `${limit.used}% used (${limit.remaining}% left)/${limit.label}`)
    .join(", ");
  if (limitsText) {
    parts.push(`limits ${limitsText}`);
  }
}

if (jsonMode) {
  const statsJson = formatStatsJson(latestUsage, limitSnapshots);
  if (statsJson) {
    process.stdout.write(JSON.stringify(statsJson));
  }
} else if (parts.length > 0) {
  process.stdout.write(parts.join(" | "));
}

function walk(value, fn) {
  if (Array.isArray(value)) {
    for (const item of value) {
      walk(item, fn);
    }
    return;
  }

  if (!value || typeof value !== "object") {
    return;
  }

  fn(value);
  for (const child of Object.values(value)) {
    walk(child, fn);
  }
}

function extractUsage(obj) {
  if (obj.method === "thread/tokenUsage/updated" && obj.params) {
    return normalizeUsage(obj.params.tokenUsage || obj.params);
  }

  if (Object.prototype.hasOwnProperty.call(obj, "tokenUsage")) {
    return normalizeUsage(obj.tokenUsage);
  }

  if (Object.prototype.hasOwnProperty.call(obj, "usage")) {
    return normalizeUsage(obj.usage);
  }

  if (obj.type === "token_usage" || obj.event === "token_usage") {
    return normalizeUsage(obj);
  }

  // Current Codex CLI rollouts emit:
  //   { type: "event_msg", payload: { type: "token_count", info: { total_token_usage: {...} } } }
  // The walker visits the inner info object; recognize it here so we don't
  // silently skip the dominant event shape (the prior parser returned blank for
  // entire sessions because no other branch matched this layout).
  if (
    Object.prototype.hasOwnProperty.call(obj, "total_token_usage") &&
    obj.total_token_usage &&
    typeof obj.total_token_usage === "object"
  ) {
    return normalizeUsage(obj.total_token_usage);
  }

  return null;
}

function parseTokenUsageLine(line) {
  const match = line.match(/^Token usage:\s*(.+)$/i);
  if (!match) {
    return null;
  }

  const fields = {};
  for (const part of match[1].matchAll(/([A-Za-z_]+)=([^\s]+)/g)) {
    fields[part[1].toLowerCase()] = part[2];
  }

  const usage = {
    total: firstDefined(fields.total, fields.total_tokens),
    input: firstDefined(fields.input, fields.input_tokens, fields.prompt_tokens),
    output: firstDefined(fields.output, fields.output_tokens, fields.completion_tokens),
    cached: firstDefined(
      fields.cached,
      fields.cache_read,
      fields.cached_input,
      fields.cached_input_tokens,
      fields.input_cached,
      fields.input_cached_tokens,
    ),
  };

  if (
    usage.total == null &&
    usage.input == null &&
    usage.output == null &&
    usage.cached == null
  ) {
    return null;
  }

  return usage;
}

function normalizeUsage(value) {
  if (!value || typeof value !== "object") {
    return null;
  }

  const total = firstNumber(value.total, value.total_tokens, value.totalTokens);
  const input = firstNumber(
    value.input,
    value.input_tokens,
    value.inputTokens,
    value.prompt_tokens,
    value.promptTokens,
  );
  const output = firstNumber(
    value.output,
    value.output_tokens,
    value.outputTokens,
    value.completion_tokens,
    value.completionTokens,
  );
  const cached = firstNumber(
    value.cached_input,
    value.cachedInput,
    value.cached_input_tokens,
    value.cachedInputTokens,
    value.input_cached_tokens,
    value.inputCachedTokens,
    value.input_tokens_details?.cached_tokens,
    value.inputTokensDetails?.cachedTokens,
    value.prompt_tokens_details?.cached_tokens,
    value.promptTokensDetails?.cachedTokens,
  );

  if (total == null && input == null && output == null && cached == null) {
    return null;
  }

  return { total, input, output, cached };
}

function firstDefined(...values) {
  for (const value of values) {
    if (value != null && value !== "") {
      return value;
    }
  }
  return null;
}

function formatStatsJson(usage, snapshots) {
  const usageJson = formatUsageJson(usage);
  const limitsJson = formatLimitsJson(snapshots);

  if (!usageJson && !limitsJson) {
    return null;
  }

  return {
    ...(usageJson || {}),
    ...(limitsJson ? { limits: limitsJson } : {}),
  };
}

// Codex CLI reports input_tokens as TOTAL including cached_input_tokens.
// Normalize to an uncached input count for parity with coord-tokens.sh and to
// avoid double-counting the cached portion (full-rate via input + discount via
// cache_read) when computing effective.
//
// Codex / OpenAI GPT-5.5 rate-card effective: input + 6*output + cache_read/10.
// See coord-tokens.sh header for OpenAI rate-card sources.
function computeCodexEffective(usage) {
  if (!usage) {
    return null;
  }
  const input_total = Number(usage.input) || 0;
  const output = Number(usage.output) || 0;
  const cache_read = Number(usage.cached) || 0;
  const input_uncached = Math.max(input_total - cache_read, 0);
  if (input_uncached === 0 && output === 0 && cache_read === 0) {
    return null;
  }
  return input_uncached + 6 * output + Math.floor(cache_read / 10);
}

function formatUsageJson(usage) {
  if (!usage) {
    return null;
  }
  const input_total = Number(usage.input) || 0;
  const output = Number(usage.output) || 0;
  const cache_read = Number(usage.cached) || 0;
  const input_uncached = Math.max(input_total - cache_read, 0);
  const effective = computeCodexEffective(usage);
  if (effective == null) {
    return null;
  }
  // Emit `input` as the uncached count for consistency with coord-tokens.sh
  // JSON output shape (downstream consumers compare like-for-like).
  return { input: input_uncached, output, cache_read, effective };
}

function formatLimitsJson(snapshots) {
  if (!snapshots || snapshots.size === 0) {
    return null;
  }

  const out = {};
  for (const label of ["5h", "week"]) {
    const snapshot = snapshots.get(label);
    if (!snapshot) {
      continue;
    }
    out[label] = {
      start: snapshot.start,
      end: snapshot.end,
      delta: snapshot.end - snapshot.start,
    };
  }
  return Object.keys(out).length > 0 ? out : null;
}

function extractRateLimits(obj) {
  if (obj.method === "account/rateLimits/updated" && obj.params) {
    return normalizeRateLimits(obj.params);
  }

  if (Object.prototype.hasOwnProperty.call(obj, "rateLimits") ||
      Object.prototype.hasOwnProperty.call(obj, "rateLimitsByLimitId") ||
      Object.prototype.hasOwnProperty.call(obj, "rate_limits")) {
    return normalizeRateLimits(obj);
  }

  return [];
}

function normalizeRateLimits(value) {
  const entries = [];

  const pushEntry = (id, limit) => {
    if (!limit || typeof limit !== "object") {
      return;
    }
    const usedPercent = firstNumber(limit.usedPercent, limit.used_percent);
    if (usedPercent == null) {
      return;
    }

    // Current Codex rollouts use `window_minutes`; older shapes used
    // `windowDurationMins` / `window_duration_mins`. Accept all three.
    const windowMins = firstNumber(
      limit.windowDurationMins,
      limit.window_duration_mins,
      limit.window_minutes,
    );
    const used = clampPercent(usedPercent);
    const remaining = clampPercent(100 - used);
    entries.push({
      id: id || "",
      label: labelForWindow(windowMins, id || ""),
      used,
      remaining,
      windowMins,
    });
  };

  if (Array.isArray(value.rateLimits)) {
    for (const limit of value.rateLimits) {
      pushEntry(limit.id || limit.limitId || "", limit);
    }
  } else if (value.rateLimits && typeof value.rateLimits === "object") {
    for (const [id, limit] of Object.entries(value.rateLimits)) {
      pushEntry(id, limit);
    }
  }

  if (value.rateLimitsByLimitId && typeof value.rateLimitsByLimitId === "object") {
    for (const [id, limit] of Object.entries(value.rateLimitsByLimitId)) {
      pushEntry(id, limit);
    }
  }

  // Current Codex CLI rollouts: payload.rate_limits = {limit_id, limit_name,
  // primary: {used_percent, window_minutes, ...}, secondary: {...}}.
  // The primary/secondary entries are the actual gauge data; the other keys
  // (limit_id, limit_name) are scalar metadata. Filter on shape rather than
  // key name so future additions don't silently get pushed as bogus entries.
  if (value.rate_limits && typeof value.rate_limits === "object") {
    for (const [id, limit] of Object.entries(value.rate_limits)) {
      if (
        limit &&
        typeof limit === "object" &&
        ("used_percent" in limit || "usedPercent" in limit)
      ) {
        pushEntry(id, limit);
      }
    }
  }

  const deduped = [];
  const seen = new Set();
  for (const entry of entries) {
    const key = `${entry.label}:${entry.remaining}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    deduped.push(entry);
  }

  deduped.sort((a, b) => {
    const aWindow = a.windowMins == null ? Number.MAX_SAFE_INTEGER : a.windowMins;
    const bWindow = b.windowMins == null ? Number.MAX_SAFE_INTEGER : b.windowMins;
    return aWindow - bWindow;
  });

  return deduped;
}

function selectPreferredLimits(limits) {
  const preferredLabels = ["5h", "week"];
  const selected = [];
  const usedLabels = new Set();

  for (const label of preferredLabels) {
    const match = limits.find((limit) => limit.label === label);
    if (match) {
      selected.push(match);
      usedLabels.add(label);
    }
  }

  if (selected.length < 2) {
    for (const limit of limits) {
      if (usedLabels.has(limit.label)) {
        continue;
      }
      selected.push(limit);
      usedLabels.add(limit.label);
      if (selected.length >= 2) {
        break;
      }
    }
  }

  return selected.slice(0, 2);
}

function labelForWindow(windowMins, id) {
  if (windowMins != null) {
    if (windowMins === 10080) {
      return "week";
    }
    if (windowMins % 10080 === 0) {
      return `${windowMins / 10080}w`;
    }
    if (windowMins === 1440) {
      return "day";
    }
    if (windowMins % 1440 === 0) {
      return `${windowMins / 1440}d`;
    }
    if (windowMins % 60 === 0) {
      return `${windowMins / 60}h`;
    }
    return `${windowMins}m`;
  }

  const text = String(id || "").toLowerCase();
  const suffix = text.match(/(?:^|[^a-z0-9])(\d+)([mhdw])(?:$|[^a-z0-9])/);
  if (suffix) {
    const amount = Number(suffix[1]);
    const unit = suffix[2];
    if (unit === "w" && amount === 1) {
      return "week";
    }
    if (unit === "d" && amount === 1) {
      return "day";
    }
    if (unit === "d" && amount === 7) {
      return "week";
    }
    return `${amount}${unit}`;
  }
  if (text.includes("week")) {
    return "week";
  }
  if (text.includes("day")) {
    return "day";
  }
  if (text.includes("hour")) {
    return "hour";
  }
  return "window";
}

function firstNumber(...values) {
  for (const value of values) {
    if (value == null || value === "") {
      continue;
    }
    const num = Number(value);
    if (Number.isFinite(num)) {
      return num;
    }
  }
  return null;
}

function clampPercent(value) {
  const rounded = Math.round(value);
  if (rounded < 0) {
    return 0;
  }
  if (rounded > 100) {
    return 100;
  }
  return rounded;
}

function formatNumber(value) {
  if (typeof value === "string" && /[A-Za-z]/.test(value)) {
    return value;
  }

  const num = Number(value);
  if (!Number.isFinite(num)) {
    return String(value);
  }

  if (Math.abs(num) >= 1000000) {
    return `${trimTrailingZeros((num / 1000000).toFixed(1))}M`;
  }
  if (Math.abs(num) >= 1000) {
    return `${trimTrailingZeros((num / 1000).toFixed(1))}K`;
  }
  return String(Math.round(num));
}

function trimTrailingZeros(text) {
  return text.replace(/\.0$/, "");
}
