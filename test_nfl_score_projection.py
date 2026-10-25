import unittest
from nfl_score_projection import project_score_lines

class NFLScoreProjectionTests(unittest.TestCase):
    def test_projects_points_separately_from_market_lines(self):
        home = {"games": 4, "points_for_per_game": 24, "points_against_per_game": 20}
        away = {"games": 5, "points_for_per_game": 21, "points_against_per_game": 23}
        result = project_score_lines(home, away, {"spread_line": -3.5, "total_line": 39.5})
        self.assertTrue(result["available"])
        self.assertEqual(result["projected_home_points"], 25.1)
        self.assertEqual(result["projected_away_points"], 20.6)
        self.assertEqual(result["projected_total_points"], 46.2)
        self.assertEqual(result["market"]["total_line"], 39.5)
        self.assertEqual(result["market_comparison"]["total_difference"], 5.7)

    def test_does_not_invent_projection_without_history(self):
        result = project_score_lines({"games": 0}, {"games": 2}, {"total_line": 42.5})
        self.assertFalse(result["available"])
        self.assertEqual(result["market"]["total_line"], 42.5)
        self.assertNotIn("projected_total_points", result)

if __name__ == "__main__":
    unittest.main()
