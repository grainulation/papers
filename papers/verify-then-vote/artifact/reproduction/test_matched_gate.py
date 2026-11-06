"""Checks that the matched comparison rejects the original confounding change."""
import copy
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from matched_gate import assert_matched, summary


class MatchedGateTests(unittest.TestCase):
    def test_rejects_nei_change_alongside_gate(self):
        off = {'evidence': {'support_factor': {'not_enough_info': 0.1}}}
        on = copy.deepcopy(off)
        on['evidence']['overturn_gate'] = 'verified'
        assert_matched(off, on)
        on['evidence']['support_factor']['not_enough_info'] = 0.5
        with self.assertRaisesRegex(AssertionError, 'second policy field'):
            assert_matched(off, on)


    def test_pairing_does_not_confuse_net_gain_with_corrections(self):
        rows = [{'baseline': 0, 'method': 1}, {'baseline': 0, 'method': 1},
                {'baseline': 1, 'method': 0}, {'baseline': 1, 'method': 1}]
        result = summary(rows, 'method', 'baseline')
        assert result == {'n': 4, 'correct': 3, 'accuracy': 0.75,
                          'baseline_correct': 2, 'corrections': 2, 'losses': 1}
