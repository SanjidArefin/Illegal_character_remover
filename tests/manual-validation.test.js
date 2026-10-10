import assert from "node:assert/strict";
import test from "node:test";
import { collisionKey, validateManualCandidate } from "../src/manual-validation.js";

const record = { path: "C:\\target\\!!!.txt", name: "!!!.txt", kind: "file" };

test("manual name validation accepts ASCII names and preserves extension", () => {
  const result = validateManualCandidate("Quarterly Notes 2", record, [], new Set());
  assert.equal(result.name, "Quarterly Notes 2");
  assert.equal(result.targetPath, "C:\\target\\Quarterly Notes 2.txt");
});

test("manual name validation rejects punctuation, tabs, and names without alphanumerics", () => {
  assert.match(validateManualCandidate("Bad-name", record, [], new Set()).error, /only A-Z/);
  assert.match(validateManualCandidate("\tNotes", record, [], new Set()).error, /only A-Z/);
  assert.match(validateManualCandidate("   ", record, [], new Set()).error, /cannot be empty/);
});

test("manual names cannot collide with existing names (case-insensitive)", () => {
  const existing = [{ path: "C:\\target\\Report.txt" }];
  assert.match(
    validateManualCandidate("report", record, existing, new Set()).error,
    /already exists/,
  );
});

test("manual names cannot collide with earlier manual renames in the session", () => {
  const usedTargets = new Set([collisionKey("C:\\target\\Shared.txt")]);
  assert.match(
    validateManualCandidate("Shared", record, [], usedTargets).error,
    /already used/,
  );
});

test("manual candidate path handling preserves a POSIX root separator", () => {
  const unixRecord = { path: "/tmp/!!!.txt", name: "!!!.txt", kind: "file" };
  const result = validateManualCandidate("Clean", unixRecord, [], new Set());
  assert.equal(result.targetPath, "/tmp/Clean.txt");
});
