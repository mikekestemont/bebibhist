// Unit tests for the topic map's data helpers. Run with: node --experimental-strip-types --test tests/
import assert from "node:assert/strict";
import { test } from "node:test";

import { decodePoints, matchQuery, regionWord, shardOf, tokens, undelta } from "../src/lib/topics.ts";

test("words are folded and function words left out, in the four languages", () => {
  assert.deepEqual(tokens("Les béguinages de Gand en het Begijnhof"), ["beguinages", "gand", "begijnhof"]);
  assert.equal(shardOf("begijnhof"), "be");
  assert.equal(shardOf("x"), "x_");
});

test("a query finds the points whose words begin with every query word", () => {
  const delta = (list: number[]) => list.map((point, i) => point - (i ? list[i - 1] : 0));
  const shards = new Map([
    ["be", { begijnhof: delta([1, 4, 9]), begijnen: delta([4, 7]), beguinage: delta([2]) }],
    ["br", { brugge: delta([4, 9, 12]) }],
  ]);
  assert.deepEqual([...matchQuery("begijn", shards)!].sort((a, b) => a - b), [1, 4, 7, 9]);
  assert.deepEqual([...matchQuery("Begijnhof Brugge", shards)!].sort((a, b) => a - b), [4, 9]);
  assert.equal(matchQuery("de het", shards), null);
  assert.deepEqual(undelta([3, 1, 5]), [3, 4, 9]);
});

test("the points file decodes to its columns, the cells on an even byte", () => {
  const n = 3;
  const evenAt = 4 + n * 7 + ((4 + n * 7) % 2);
  const buffer = new ArrayBuffer(evenAt + n * 2);
  new Uint32Array(buffer, 0, 1)[0] = n;
  new Uint16Array(buffer, 4, n).set([0, 32768, 65535]);
  new Uint16Array(buffer, 4 + n * 2, n).set([65535, 0, 0]);
  new Uint8Array(buffer, 4 + n * 4, n).set([190, 0, 225]);
  new Uint8Array(buffer, 4 + n * 5, n).set([1, 2, 4]);
  new Uint8Array(buffer, 4 + n * 6, n).set([0, 8, 0]);
  new Uint16Array(buffer, evenAt, n).set([5, 599, 0]);
  const points = decodePoints(buffer);
  assert.equal(points.n, 3);
  assert.equal(points.x[2], 1);
  assert.ok(Math.abs(points.x[1] - 0.5) < 0.001);
  assert.deepEqual([...points.year], [190, 0, 225]);
  assert.deepEqual([...points.cell], [5, 599, 0]);
});

test("a region's search word has one length, so none begins another", () => {
  assert.equal(regionWord("r2.10"), "rg_2010");
  assert.equal(regionWord("r1.1"), "rg_1001");
  assert.ok(!regionWord("r1.10").startsWith(regionWord("r1.1")));
  assert.equal(regionWord("r3.599"), "rg_3599");
});
