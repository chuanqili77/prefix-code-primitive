# PrefixCode — prefix-free code certificate primitive

一组二进制码字是否无前缀（没有任何一个码字是另一个码字的前缀）的认证原语 —— 霍夫曼编码所依赖的性质。

PrefixCode is a deterministic prefix-free code certificate primitive: it certifies whether a set of binary codewords is prefix-free — no codeword is a prefix of another, the property Huffman codes rely on. The verdict is fixed by the full per-pair boolean vector.

- Network: Stable Studionet, Chain ID 61999, RPC https://studio.genlayer.com/api
- Contract: `0xc660b5e848558C13088B89E7d215Ba3562E6a16f`
- Explorer: https://explorer-studio.genlayer.com/address/0xc660b5e848558C13088B89E7d215Ba3562E6a16f
- Source: `contracts/prefix_code.py`
- Source SHA-256: `c91d212b83bc4591a8afaafee2af8b1554a9b45550d6f1ee02528c300e6dff87`
- Deployed code matches the source byte for byte (checked with `gen_getContractCode`).

## Mechanism / 机制

One thing, one fixed enumeration table, full-vector exact equality, one explicit counterexample on-chain.

`create_case(case_id, codewords_json, claimed_pair_results_json, claimed_verdict)` certifies one set of binary codewords:

1. Codewords: 2–16 unique non-empty binary strings (characters only `0`/`1`, each 1–32 characters long).
2. For every unordered pair (i, j) with i < j, in index order, the contract recomputes `pair_result_k = True` iff neither codeword is a prefix of the other. The number of pairs is n(n−1)/2 for n codewords.
3. The verdict is a fixed enumeration over the full pair-result vector:

   | Verdict | Meaning |
   | --- | --- |
   | `PREFIX_FREE` | Every pair result is True — no codeword is a prefix of another. |
   | `COLLISION` | At least one pair result is False — some codeword is a prefix of another. |

4. The witness is the first colliding pair in index order: `{pair_index, i, j, word_i, word_j, prefix}`, where `prefix` is the shorter word that is a prefix of the longer one (or `null` when the verdict is `PREFIX_FREE`). The full pair-result vector is stored with the record.
5. **Equivalence check, zero tolerance:** the caller-proposed pair-result vector must equal the recomputed vector element by element, and the caller-proposed verdict must equal the recomputed verdict. Any single entry flipped, or a verdict that does not match the recomputed vector, fails the call (`PAIR_MISMATCH` / `VERDICT_MISMATCH`) and creates no record. No aggregation, no scores, no thresholds.

No LLM is used: this is pure deterministic string comparison. Leader and validators each recompute the same vector from the same locked inputs; there is no judgement call anywhere in the decision. The consequence is informational only: the record states the verdict and the witness. No GEN moves, no money changes hands.

## State machine / 状态机

```
create_case() --> DECIDED (terminal, verdict immutable)
```

- A record is created once, already in state `DECIDED`. There is no update method, so the verdict can never change.
- A second `create_case` with the same `case_id` fails with `ALREADY_EXISTS`.
- A failed claim (wrong vector or wrong verdict) creates no record at all — the same `case_id` can be retried with the correct claim.

## How to call / 调用方法

All codewords are binary strings inside JSON. All on-chain values are English.

```js
// Certify a prefix-free code: ["0", "10", "110", "111"]
// pairs (0,1) (0,2) (0,3) (1,2) (1,3) (2,3) -> all True
// -> PREFIX_FREE, witness null
create_case(
  "C-FREE-01",
  JSON.stringify(["0", "10", "110", "111"]),
  JSON.stringify([true, true, true, true, true, true]),
  "PREFIX_FREE",
);
// -> the stored record, state DECIDED
```

```js
// Certify a colliding code: ["0", "01"]
// pair (0,1): "0" is a prefix of "01" -> False
// -> COLLISION, witness {pair_index: 0, i: 0, j: 1, word_i: "0", word_j: "01", prefix: "0"}
create_case(
  "C-COLL-01",
  JSON.stringify(["0", "01"]),
  JSON.stringify([false]),
  "COLLISION",
);
```

```js
// A wrong claim fails on-chain and creates no record:
// same codewords as C-FREE-01, but the last pair result flipped to false
// -> ERROR PAIR_MISMATCH
create_case(
  "C-BAD-01",
  JSON.stringify(["0", "10", "110", "111"]),
  JSON.stringify([true, true, true, true, true, false]),
  "PREFIX_FREE",
);
```

Reads:

```js
get_protocol(); // protocol, bounds, verdicts, states, pair rule
get_case("C-FREE-01"); // id, codewords, pair_results, verdict, witness, state, creator
get_stats(); // total, prefix_free, collision
```

## Evidence / 证据

All transactions FINALIZED with MAJORITY_AGREE consensus. Full machine-readable evidence: [`evidence.json`](evidence.json). Deployment record: [`deployment.json`](deployment.json).

| Case | Transaction | Result |
| --- | --- | --- |
| Deploy | `0x4d135161c69c94a4ce7aa906cc41bd72e9c5d74e0c2aff4188fe82e0037f3eb3` | FINALIZED, contract `0xc660b5e848558C13088B89E7d215Ba3562E6a16f` |
| C-FREE-01 codewords ["0","10","110","111"] | `0x772d98881a8b09db8e4c920fbed284b853290b62c989b7cd8a25aa77e83f0127` | FINALIZED / SUCCESS — pair_results all True, verdict PREFIX_FREE, witness null |
| C-BAD-01 same codewords, last pair result flipped to False | `0xfdfdc3240698e97bce6917056fde022ee4b9d6ca8ba1a30d783bfa9291365f5d` | FINALIZED / ERROR `PAIR_MISMATCH` — the flipped claim was rejected; no record created |
| C-COLL-01 codewords ["0","01"] | `0xcb0865352580959784365ef8e74b82a471cb681459d6ed5ed88571ead290b780` | FINALIZED / SUCCESS — pair_results [false], verdict COLLISION, witness pair (0,1), prefix "0" |

Final stats read back live: total 2 — prefix_free 1, collision 1.

## Reuse / 复用价值

Any binary codebook — a Huffman code table, a prefix code for a compression scheme, a variable-length coding table — can be certified with this primitive: send the codewords with the claimed pair-result vector and verdict, and consensus either confirms the code is prefix-free or names the first colliding pair. The same contract also serves as the deterministic core for any pairwise prefix check.

## Tests / 测试

`tests/test_prefix_code.py` runs the real contract source locally with a stubbed host module (local mock only — not chain consensus evidence). It covers the prefix-free verdict, the collision verdict with witness, first-collision selection, tampered vectors, wrong-verdict labels, input validation, and the immutable-verdict rule:

```bash
npm test   # python3 tests/test_prefix_code.py — 8 tests
```

## Known limitations / 已知限制

- The codewords are caller-supplied: the contract certifies the codewords as given, but it does not verify they came from a real encoder. A certificate is only as honest as its input codewords.
- There is no independent anchor for the codewords: the contract checks the claimed pair vector and verdict against the codewords exactly, but nothing outside the chain vouches for where the codewords came from.
- The consequence is informational only: the record states the verdict and the witness; no GEN moves and no money changes hands.
- Codeword sets are capped at 16 words of at most 32 bits each; larger codebooks must be split into several cases.
