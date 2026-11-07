"""Synthetic, network-free checks of scoring rules and observation boundaries."""

from copy import deepcopy
import unittest

from fpl.scoring import aggregate, calculate, total


def observation(**changes):
    """Explicit zero facts describe an observed fixture, never missing data."""
    record = {
        "season": "2026/27", "element": 4, "fixture": 20, "round": 2,
        "value": 80, "fetched_at": "2026-11-07T17:00:00+00:00",
        "minutes": 90, "goals_scored": 0, "assists": 0,
        "clean_sheets": 0, "saves": 0, "penalties_saved": 0,
        "penalties_missed": 0, "goals_conceded": 0, "own_goals": 0,
        "yellow_cards": 0, "red_cards": 0, "bonus": 0,
        "defensive_contribution": 0,
    }
    record.update(changes)
    return record


class FixtureScoringTests(unittest.TestCase):
    def test_appearance_boundaries(self):
        for minutes, points in ((0, 0), (1, 1), (59, 1), (60, 2), (90, 2)):
            with self.subTest(minutes=minutes):
                self.assertEqual(calculate(observation(minutes=minutes), 2)["minutes"], points)

    def test_clean_sheet_minutes_and_position(self):
        for position, award in ((1, 4), (2, 4), (3, 1), (4, 0)):
            for minutes in (59, 60):
                with self.subTest(position=position, minutes=minutes):
                    points = calculate(observation(minutes=minutes, clean_sheets=1), position)
                    self.assertEqual(points["clean_sheets"], award if minutes == 60 else 0)

    def test_clean_sheet_uses_player_award_not_concession_inference(self):
        # A team clean sheet does not manufacture missing player eligibility.
        self.assertEqual(calculate(observation(clean_sheets=0, goals_conceded=0), 2)["clean_sheets"], 0)
        # Player eligibility can survive substitution before the team concedes.
        record = observation(clean_sheets=1, team_h_score=1, team_a_score=1)
        self.assertEqual(calculate(record, 2)["clean_sheets"], 4)

    def test_goal_weights_and_assists(self):
        for position, goal_points in ((1, 10), (2, 6), (3, 5), (4, 4)):
            with self.subTest(position=position):
                points = calculate(observation(goals_scored=2, assists=1), position)
                self.assertEqual(points["goals_scored"], 2 * goal_points)
                self.assertEqual(points["assists"], 3)

    def test_save_rounding(self):
        for saves, points in ((0, 0), (2, 0), (3, 1), (5, 1), (6, 2)):
            with self.subTest(saves=saves):
                self.assertEqual(calculate(observation(saves=saves), 1)["saves"], points)

    def test_concession_rounding_and_position(self):
        for position in (1, 2, 3, 4):
            for conceded, deduction in ((0, 0), (1, 0), (2, -1), (3, -1), (4, -2)):
                with self.subTest(position=position, conceded=conceded):
                    points = calculate(observation(goals_conceded=conceded), position)
                    self.assertEqual(points["goals_conceded"], deduction if position <= 2 else 0)

    def test_dc_positional_thresholds_and_cap(self):
        cases = {
            1: ((0, 0), (10, 0), (12, 0), (30, 0)),
            2: ((9, 0), (10, 2), (11, 2), (20, 2), (30, 2)),
            3: ((10, 0), (11, 0), (12, 2), (13, 2), (24, 2)),
            4: ((10, 0), (11, 0), (12, 2), (13, 2), (24, 2)),
        }
        for position, boundaries in cases.items():
            for actions, award in boundaries:
                with self.subTest(position=position, actions=actions):
                    points = calculate(observation(defensive_contribution=actions), position)
                    self.assertEqual(points["defensive_contribution"], award)

    def test_deductions_and_bonus(self):
        points = calculate(observation(penalties_missed=1, own_goals=1,
                                       yellow_cards=1, red_cards=1, bonus=3), 4)
        self.assertEqual({k: points[k] for k in (
            "penalties_missed", "own_goals", "yellow_cards", "red_cards", "bonus")},
            {"penalties_missed": -2, "own_goals": -2, "yellow_cards": -1,
             "red_cards": -3, "bonus": 3})
        self.assertEqual(total(points), -3)

    def test_penalty_save_is_separate_from_save_rounding(self):
        points = calculate(observation(penalties_saved=1, saves=3), 1)
        self.assertEqual(points["penalties_saved"], 5)
        self.assertEqual(points["saves"], 1)
        self.assertEqual(total(points), 8)

    def test_missing_or_invalid_applicable_fact_is_not_zero(self):
        for field, position in (("minutes", 2), ("assists", 3), ("clean_sheets", 2),
                                ("saves", 1), ("goals_conceded", 2),
                                ("defensive_contribution", 4)):
            for invalid in (None, -1, "0", 0.0, False):
                with self.subTest(field=field, invalid=invalid):
                    points = calculate(observation(**{field: invalid}), position)
                    self.assertIsNone(points[field])
                    self.assertIsNone(total(points))
            record = observation()
            del record[field]
            with self.subTest(field=field, absent=True):
                self.assertIsNone(total(calculate(record, position)))

    def test_inapplicable_categories_do_not_require_facts(self):
        record = observation()
        for field in ("saves", "penalties_saved", "goals_conceded", "clean_sheets"):
            del record[field]
        points = calculate(record, 4)
        self.assertEqual(total(points), 2)
        goalkeeper = observation()
        del goalkeeper["defensive_contribution"]
        self.assertEqual(calculate(goalkeeper, 1)["defensive_contribution"], 0)

    def test_unknown_position_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown position"):
            calculate(observation(), 5)


class GameweekScoringTests(unittest.TestCase):
    def test_double_rounds_saves_and_concessions_per_fixture(self):
        records = [observation(fixture=20, saves=2, goals_conceded=1),
                   observation(fixture=21, saves=2, goals_conceded=1)]
        # Four saves and two concessions across the GW earn neither award nor
        # deduction: each fixture is below both thresholds. Appearances give 4.
        self.assertEqual(aggregate(records, [20, 21], 1),
                         {"state": "complete", "total": 4})

    def test_double_dc_is_thresholded_and_capped_per_fixture(self):
        for counts, expected in (((5, 5), 4), ((10, 10), 8), ((20, 0), 6)):
            with self.subTest(counts=counts):
                records = [observation(fixture=20, defensive_contribution=counts[0]),
                           observation(fixture=21, defensive_contribution=counts[1])]
                self.assertEqual(aggregate(records, [20, 21], 2),
                                 {"state": "complete", "total": expected})

    def test_blank_missing_and_observed_zero_minutes_are_distinct(self):
        self.assertEqual(aggregate([], [], 2), {"state": "blank", "total": 0})
        self.assertEqual(aggregate([], [20], 2), {"state": "missing", "total": None})
        self.assertEqual(aggregate([observation(minutes=0)], [20], 2),
                         {"state": "complete", "total": 0})

    def test_missing_second_fixture_or_fact_makes_total_unknown(self):
        self.assertEqual(aggregate([observation()], [20, 21], 2),
                         {"state": "missing", "total": None})
        self.assertEqual(aggregate([observation(defensive_contribution=None)], [20], 2),
                         {"state": "missing", "total": None})

    def test_unexpected_fixture_is_a_coverage_mismatch(self):
        self.assertEqual(aggregate([observation(fixture=21)], [20], 2),
                         {"state": "missing", "total": None})

    def test_duplicate_observations_cannot_double_count(self):
        with self.assertRaisesRegex(ValueError, "Duplicate fixture"):
            aggregate([observation(), observation()], [20], 2)

    def test_corrected_observation_replaces_not_adds_to_old_revision(self):
        earlier = observation(defensive_contribution=9)
        corrected = {**earlier, "defensive_contribution": 10,
                     "fetched_at": "2026-11-07T18:00:00+00:00"}
        self.assertEqual(aggregate([earlier], [20], 2)["total"], 2)
        self.assertEqual(aggregate([corrected], [20], 2)["total"], 4)
        self.assertEqual(earlier["defensive_contribution"], 9)
        for field in ("season", "element", "fixture", "round", "value"):
            self.assertEqual(earlier[field], corrected[field])
        with self.assertRaises(ValueError):
            aggregate([earlier, corrected], [20], 2)

    def test_replay_is_stable_order_independent_and_does_not_mutate_inputs(self):
        records = [observation(fixture=20, clean_sheets=1, defensive_contribution=10),
                   observation(fixture=21, goals_scored=1, yellow_cards=1)]
        original = deepcopy(records)
        first = aggregate(records, [20, 21], 2)
        self.assertEqual(first, {"state": "complete", "total": 15})
        self.assertEqual(aggregate(records, [20, 21], 2), first)
        self.assertEqual(aggregate(list(reversed(records)), [21, 20], 2), first)
        self.assertEqual(records, original)


if __name__ == "__main__":
    unittest.main()
