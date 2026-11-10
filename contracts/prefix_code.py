# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""PrefixCode: prefix-free code certificate primitive.

One thing: certify whether a set of binary codewords is prefix-free
(no codeword is a prefix of another — the property Huffman codes
rely on). Anyone may submit a certification; the result is
recomputable by anyone from the codewords alone.

For every unordered pair (i, j) with i < j, in index order, the
contract recomputes pair_result_k = True iff neither codeword is a
prefix of the other. The number of pairs is n(n-1)/2 for n codewords.
The verdict is a fixed enumeration over the full pair-result vector:

  PREFIX_FREE — every pair_result is True.
  COLLISION   — at least one pair_result is False.

The witness is the first colliding pair (in index order):
{pair_index, i, j, word_i, word_j, prefix}, where prefix is the
shorter word that is a prefix of the longer one (or null when the
verdict is PREFIX_FREE). The full pair-result vector is stored with
the record.

Equivalence check: create_case takes a caller-proposed pair-result
vector and a caller-proposed verdict and requires EXACT element-wise
equality with the vector the contract recomputes deterministically,
plus exact equality of the verdict. Any single entry flipped, or a
verdict that does not match the recomputed vector, fails the call
and creates no record. Leader and validators each recompute the
same vector from the same locked inputs; there is no judgement call
anywhere in the decision. Zero tolerance: no aggregation, no scores,
no thresholds.

State machine: a record is created once, in state DECIDED, and the
verdict is immutable — there is no update method. A second
create_case with the same case_id always fails.

No LLM is used: this is pure deterministic string comparison. The
consequence is informational only: the record states the verdict and
the witness. No GEN moves, no money changes hands.
"""

import json

from genlayer import *

PROTOCOL = "prefixcode-1"
MIN_WORDS = 2
MAX_WORDS = 16
MIN_WORD_LEN = 1
MAX_WORD_LEN = 32
VERDICTS = ["PREFIX_FREE", "COLLISION"]
ID_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"


def pack(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def need(ok, code):
    if not ok:
        raise gl.vm.UserError("EXPECTED: " + code)


def unique_pairs(pairs):
    d = {}
    for key, value in pairs:
        need(key not in d, "DUPLICATE_JSON_KEY")
        d[key] = value
    return d


def parse(raw):
    return json.loads(raw, object_pairs_hook=unique_pairs) if isinstance(raw, str) else raw


def is_prefix(shorter, longer):
    """Pure function: True iff shorter is a strict prefix of longer."""
    return len(shorter) < len(longer) and longer.startswith(shorter)


def pair_collides(word_i, word_j):
    """Pure function: True iff one word is a prefix of the other."""
    return is_prefix(word_i, word_j) or is_prefix(word_j, word_i)


def compute_pair_results(codewords):
    """Pure function: the full per-pair boolean vector, index order i<j."""
    results = []
    for i in range(len(codewords)):
        for j in range(i + 1, len(codewords)):
            results.append(not pair_collides(codewords[i], codewords[j]))
    return results


def compute_verdict(pair_results):
    """Pure function: the fixed-enumeration verdict of a pair vector."""
    return "PREFIX_FREE" if all(pair_results) else "COLLISION"


def compute_witness(codewords, pair_results):
    """Pure function: first colliding pair and its prefix word, or null."""
    k = 0
    for i in range(len(codewords)):
        for j in range(i + 1, len(codewords)):
            if not pair_results[k]:
                word_i = codewords[i]
                word_j = codewords[j]
                prefix = word_i if len(word_i) < len(word_j) else word_j
                return {
                    "pair_index": k,
                    "i": i,
                    "j": j,
                    "word_i": word_i,
                    "word_j": word_j,
                    "prefix": prefix,
                }
            k += 1
    return None


class PrefixCode(gl.Contract):
    cases: TreeMap[str, str]
    total_cases: u32
    prefix_free_count: u32
    collision_count: u32

    def __init__(self):
        self.total_cases = u32(0)
        self.prefix_free_count = u32(0)
        self.collision_count = u32(0)

    @gl.public.view
    def get_protocol(self) -> str:
        return pack({
            "protocol": PROTOCOL,
            "min_words": MIN_WORDS,
            "max_words": MAX_WORDS,
            "min_word_len": MIN_WORD_LEN,
            "max_word_len": MAX_WORD_LEN,
            "verdicts": VERDICTS,
            "states": ["DECIDED"],
            "pair_rule": "neither_word_is_a_prefix_of_the_other",
            "equivalence": "full_pair_vector_exact_equality_zero_tolerance",
        })

    @gl.public.view
    def get_case(self, case_id: str) -> str:
        return self.cases.get(case_id, "")

    @gl.public.view
    def get_stats(self) -> str:
        return pack({
            "total": int(self.total_cases),
            "prefix_free": int(self.prefix_free_count),
            "collision": int(self.collision_count),
        })

    @gl.public.write
    def create_case(
        self,
        case_id: str,
        codewords_json: str,
        claimed_pair_results_json: str,
        claimed_verdict: str,
    ) -> str:
        need(type(case_id) is str and 1 <= len(case_id) <= 64, "CASE_ID_LENGTH")
        need(all(c in ID_CHARS for c in case_id), "CASE_ID_CHARS")
        need(not self.cases.get(case_id, ""), "ALREADY_EXISTS")
        need(
            len(codewords_json) <= 2000
            and len(claimed_pair_results_json) <= 2000,
            "INPUT_BOUND",
        )
        codewords = parse(codewords_json)
        claimed_pair_results = parse(claimed_pair_results_json)
        need(type(codewords) is list, "LIST_INPUT")
        need(type(claimed_pair_results) is list, "CLAIMED_LIST_INPUT")
        need(MIN_WORDS <= len(codewords) <= MAX_WORDS, "WORD_COUNT_2_16")
        need(
            all(
                type(w) is str
                and MIN_WORD_LEN <= len(w) <= MAX_WORD_LEN
                and all(c in "01" for c in w)
                for w in codewords
            ),
            "WORD_FORMAT",
        )
        need(len(set(codewords)) == len(codewords), "DUPLICATE_WORD")
        pair_count = len(codewords) * (len(codewords) - 1) // 2
        need(len(claimed_pair_results) == pair_count, "CLAIMED_LENGTH")
        need(
            all(type(r) is bool for r in claimed_pair_results),
            "CLAIMED_FORMAT",
        )
        need(claimed_verdict in VERDICTS, "VERDICT_UNKNOWN")
        pair_results = compute_pair_results(codewords)
        verdict = compute_verdict(pair_results)
        # Equivalence: the full pair-result vector must match exactly,
        # element by element, zero tolerance. Checked before the verdict
        # so a wrong vector can never slip through behind a right label.
        need(claimed_pair_results == pair_results, "PAIR_MISMATCH")
        need(claimed_verdict == verdict, "VERDICT_MISMATCH")
        record = {
            "id": case_id,
            "codewords": codewords,
            "pair_results": pair_results,
            "verdict": verdict,
            "witness": compute_witness(codewords, pair_results),
            "state": "DECIDED",
            "creator": str(gl.message.sender_address).lower(),
        }
        self.cases[case_id] = pack(record)
        self.total_cases = self.total_cases + u32(1)
        if verdict == "PREFIX_FREE":
            self.prefix_free_count = self.prefix_free_count + u32(1)
        else:
            self.collision_count = self.collision_count + u32(1)
        return pack(record)
