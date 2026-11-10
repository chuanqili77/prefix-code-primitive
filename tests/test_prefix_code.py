"""Local mock tests for PrefixCode. NOT chain consensus evidence.

The real contract source (contracts/prefix_code.py) is imported with
a stubbed `genlayer` module: the host fakes the VM (message, storage)
so the contract's deterministic logic can be exercised locally.
Passing here proves the pair logic and the guards in this file;
on-chain proof comes only from the FINALIZED transactions in
evidence.json.
"""
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path


class Map(dict):
    @classmethod
    def __class_getitem__(cls, value):
        return cls


class _Write:
    def __call__(self, f):
        return f

    def payable(self, f):
        return f


identity = lambda f: f


class UserError(Exception):
    pass


host = types.SimpleNamespace(
    Contract=object,
    public=types.SimpleNamespace(view=identity, write=_Write()),
    message=types.SimpleNamespace(sender_address="0x" + "1" * 40, value=0),
    evm=types.SimpleNamespace(contract_interface=identity),
    vm=types.SimpleNamespace(UserError=UserError, Return=object),
    nondet=types.SimpleNamespace(),
)
sdk = types.ModuleType("genlayer")
sdk.gl, sdk.TreeMap, sdk.u32, sdk.u256 = host, Map, int, int
sdk.Address = lambda a: a
sys.modules["genlayer"] = sdk

spec = importlib.util.spec_from_file_location(
    "prefix_code", Path(__file__).parents[1] / "contracts" / "prefix_code.py"
)
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)

CREATOR = "0x" + "1" * 40
FREE_WORDS = ["0", "10", "110", "111"]
COLLIDING_WORDS = ["0", "01"]


def expect_error(fn, code):
    with unittest.TestCase().assertRaises(UserError) as ctx:
        fn()
    assert code in str(ctx.exception), f"expected {code}, got {ctx.exception}"


class PrefixCodeTests(unittest.TestCase):
    def setUp(self):
        host.message.sender_address = CREATOR
        host.message.value = 0
        self.c = r.PrefixCode()
        self.c.cases = Map()
        self.c.total_cases = 0
        self.c.prefix_free_count = 0
        self.c.collision_count = 0

    def create(self, cid, words, pair_results, verdict):
        return self.c.create_case(
            cid,
            json.dumps(words),
            json.dumps(pair_results),
            verdict,
        )

    def test_protocol(self):
        p = json.loads(self.c.get_protocol())
        self.assertEqual(p["protocol"], "prefixcode-1")
        self.assertEqual(p["verdicts"], ["PREFIX_FREE", "COLLISION"])
        self.assertEqual(p["states"], ["DECIDED"])
        self.assertEqual(p["min_words"], 2)
        self.assertEqual(p["max_words"], 16)
        self.assertEqual(p["max_word_len"], 32)

    def test_pair_results_and_verdicts(self):
        self.assertEqual(r.compute_pair_results(FREE_WORDS), [True] * 6)
        self.assertEqual(r.compute_verdict([True] * 6), "PREFIX_FREE")
        self.assertEqual(r.compute_pair_results(COLLIDING_WORDS), [False])
        self.assertEqual(r.compute_verdict([False]), "COLLISION")
        self.assertEqual(r.compute_verdict([True, False, True]), "COLLISION")
        # "01" is a prefix of "010"; "1" is a prefix of "10".
        self.assertEqual(r.compute_pair_results(["01", "010", "1", "10"]), [False, True, True, True, True, False])
        # Equal-length words can never collide.
        self.assertEqual(r.compute_pair_results(["00", "01", "10", "11"]), [True] * 6)
        # Single-bit words only collide when equal, which duplicates forbid.
        self.assertEqual(r.compute_pair_results(["0", "1"]), [True])

    def test_witness_is_first_collision(self):
        self.assertIsNone(r.compute_witness(FREE_WORDS, [True] * 6))
        self.assertEqual(
            r.compute_witness(COLLIDING_WORDS, [False]),
            {"pair_index": 0, "i": 0, "j": 1, "word_i": "0", "word_j": "01", "prefix": "0"},
        )
        # Two collisions: pairs (0,1) "0"/"01" and (0,2) "0"/"010";
        # the witness is the first one in index order.
        words = ["0", "01", "010", "11"]
        results = r.compute_pair_results(words)
        self.assertEqual(results, [False, False, True, False, True, True])
        self.assertEqual(
            r.compute_witness(words, results),
            {"pair_index": 0, "i": 0, "j": 1, "word_i": "0", "word_j": "01", "prefix": "0"},
        )
        # Longer word first in the pair: prefix is still the shorter one.
        self.assertEqual(
            r.compute_witness(["010", "01"], [False]),
            {"pair_index": 0, "i": 0, "j": 1, "word_i": "010", "word_j": "01", "prefix": "01"},
        )

    def test_good_prefix_free(self):
        out = json.loads(self.create("C-FREE", FREE_WORDS, [True] * 6, "PREFIX_FREE"))
        self.assertEqual(out["verdict"], "PREFIX_FREE")
        self.assertEqual(out["pair_results"], [True] * 6)
        self.assertIsNone(out["witness"])
        self.assertEqual(out["state"], "DECIDED")
        back = json.loads(self.c.get_case("C-FREE"))
        self.assertEqual(back, out)
        stats = json.loads(self.c.get_stats())
        self.assertEqual(stats, {"total": 1, "prefix_free": 1, "collision": 0})

    def test_good_collision_with_witness(self):
        out = json.loads(self.create("C-COLL", COLLIDING_WORDS, [False], "COLLISION"))
        self.assertEqual(out["verdict"], "COLLISION")
        self.assertEqual(out["pair_results"], [False])
        self.assertEqual(
            out["witness"],
            {"pair_index": 0, "i": 0, "j": 1, "word_i": "0", "word_j": "01", "prefix": "0"},
        )
        stats = json.loads(self.c.get_stats())
        self.assertEqual(stats, {"total": 1, "prefix_free": 0, "collision": 1})

    def test_bad_claims_fail_and_create_nothing(self):
        # Prefix-free set, but one pair result flipped to False.
        expect_error(
            lambda: self.create("C-BAD", FREE_WORDS, [True, True, True, True, True, False], "PREFIX_FREE"),
            "PAIR_MISMATCH",
        )
        self.assertEqual(self.c.get_case("C-BAD"), "")
        # Right vector, wrong verdict label.
        expect_error(
            lambda: self.create("C-BAD", FREE_WORDS, [True] * 6, "COLLISION"),
            "VERDICT_MISMATCH",
        )
        self.assertEqual(self.c.get_case("C-BAD"), "")
        # Colliding set claimed prefix-free: vector and verdict both wrong,
        # the vector check fires first.
        expect_error(
            lambda: self.create("C-BAD", COLLIDING_WORDS, [True], "PREFIX_FREE"),
            "PAIR_MISMATCH",
        )
        self.assertEqual(self.c.get_case("C-BAD"), "")
        # Wrong-length claimed vector.
        expect_error(
            lambda: self.create("C-BAD", FREE_WORDS, [True] * 5, "PREFIX_FREE"),
            "CLAIMED_LENGTH",
        )
        # The correct claim then succeeds on the same id.
        out = json.loads(self.create("C-BAD", FREE_WORDS, [True] * 6, "PREFIX_FREE"))
        self.assertEqual(out["verdict"], "PREFIX_FREE")
        self.assertEqual(json.loads(self.c.get_stats())["total"], 1)

    def test_validation(self):
        expect_error(
            lambda: self.create("C-X", ["0", "2"], [True], "PREFIX_FREE"),
            "WORD_FORMAT",
        )
        expect_error(
            lambda: self.create("C-X", ["0", "0"], [True], "PREFIX_FREE"),
            "DUPLICATE_WORD",
        )
        expect_error(
            lambda: self.create("C-X", ["0", ""], [True], "PREFIX_FREE"),
            "WORD_FORMAT",
        )
        expect_error(
            lambda: self.create("C-X", ["0"], [], "PREFIX_FREE"),
            "WORD_COUNT_2_16",
        )
        expect_error(
            lambda: self.create("C-X", ["0"] * 17, [True] * 136, "PREFIX_FREE"),
            "WORD_COUNT_2_16",
        )
        expect_error(
            lambda: self.create("C-X", ["0", "1" * 33], [True], "PREFIX_FREE"),
            "WORD_FORMAT",
        )
        expect_error(
            lambda: self.create("C-X", FREE_WORDS, [True] * 6, "UNKNOWN"),
            "VERDICT_UNKNOWN",
        )
        expect_error(
            lambda: self.create("bad id!", FREE_WORDS, [True] * 6, "PREFIX_FREE"),
            "CASE_ID_CHARS",
        )

    def test_verdict_is_immutable(self):
        self.create("C-ONE", FREE_WORDS, [True] * 6, "PREFIX_FREE")
        # Same id again, even with a different (correct) claim, fails.
        expect_error(
            lambda: self.create("C-ONE", COLLIDING_WORDS, [False], "COLLISION"),
            "ALREADY_EXISTS",
        )
        back = json.loads(self.c.get_case("C-ONE"))
        self.assertEqual(back["verdict"], "PREFIX_FREE")
        self.assertEqual(back["pair_results"], [True] * 6)


if __name__ == "__main__":
    unittest.main()
