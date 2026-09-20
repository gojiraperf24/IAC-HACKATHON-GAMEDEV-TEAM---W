"""Unit tests for mafia/roles.py - pure logic, no sockets/I-O involved.

Run with: python -m unittest discover tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mafia import roles


class ComputeRolesTests(unittest.TestCase):
    def test_rejects_fewer_than_four(self):
        for n in (0, 1, 2, 3):
            with self.assertRaises(ValueError):
                roles.compute_roles(n)

    def test_counts_sum_to_total_for_a_wide_range(self):
        for n in range(4, 30):
            grad_student, mentor, warden, professor, student = roles.compute_roles(n)
            self.assertEqual(grad_student + mentor + warden + professor + student, n)

    def test_exactly_one_grad_student_always(self):
        for n in range(4, 30):
            grad_student, _, _, _, _ = roles.compute_roles(n)
            self.assertEqual(grad_student, 1)

    def test_mentor_present_from_minimum_players(self):
        for n in range(4, 30):
            _, mentor, _, _, _ = roles.compute_roles(n)
            self.assertEqual(mentor, 1)

    def test_warden_present_from_minimum_players(self):
        for n in range(4, 30):
            _, _, warden, _, _ = roles.compute_roles(n)
            self.assertEqual(warden, 1)

    def test_professor_only_from_seven_players_up(self):
        for n in (4, 5, 6):
            _, _, _, professor, _ = roles.compute_roles(n)
            self.assertEqual(professor, 0)
        for n in range(7, 30):
            _, _, _, professor, _ = roles.compute_roles(n)
            self.assertEqual(professor, 1)

    def test_grad_student_never_outnumbers_everyone_else_at_assignment(self):
        # The game would be trivially unwinnable if the Grad Student started
        # already equal to or greater than everyone else.
        for n in range(4, 30):
            grad_student, mentor, warden, professor, student = roles.compute_roles(n)
            good = mentor + warden + professor + student
            self.assertLess(grad_student, good, f"n={n}: grad_student={grad_student} good={good}")

    def test_student_count_never_negative(self):
        for n in range(4, 30):
            _, _, _, _, student = roles.compute_roles(n)
            self.assertGreaterEqual(student, 0)


class BuildRolePoolTests(unittest.TestCase):
    def test_pool_size_matches_player_count(self):
        for n in range(4, 20):
            pool = roles.build_role_pool(n)
            self.assertEqual(len(pool), n)

    def test_pool_contains_only_known_roles(self):
        known = {roles.STUDENT, roles.GRAD_STUDENT, roles.MENTOR, roles.WARDEN, roles.PROFESSOR}
        pool = roles.build_role_pool(10)
        self.assertTrue(set(pool).issubset(known))

    def test_professor_absent_below_seven_players(self):
        pool = roles.build_role_pool(6)
        self.assertNotIn(roles.PROFESSOR, pool)

    def test_every_role_has_a_description(self):
        for role in (roles.STUDENT, roles.GRAD_STUDENT, roles.MENTOR, roles.WARDEN, roles.PROFESSOR):
            self.assertIn(role, roles.DESCRIPTIONS)
            self.assertTrue(roles.DESCRIPTIONS[role])


if __name__ == "__main__":
    unittest.main()
