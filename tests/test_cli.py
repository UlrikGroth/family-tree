"""Exercise the terminal interface against a fresh, on-disk family database."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIN = PROJECT_ROOT / "main.py"


class FamilyTreeCLITests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database = Path(self.temporary_directory.name) / "family.sqlite3"

    def run_cli(self, *arguments, expected_code=0, stdin_text=""):
        result = subprocess.run(
            [
                sys.executable,
                str(MAIN),
                "--database",
                str(self.database),
                *map(str, arguments),
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            input=stdin_text,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
        self.assertEqual(
            result.returncode,
            expected_code,
            msg=f"Command: {arguments!r}\n{result.stdout}\n{result.stderr}",
        )
        self.last_stderr = result.stderr
        return result.stdout

    def add_person(self, name, expected_id, *options):
        output = self.run_cli("add", name, *options)
        self.assertRegex(output, rf"\b{expected_id}\b")

    def test_people_and_profile_persist_between_commands(self):
        self.add_person(
            "Søren Jensen",
            1,
            "--born",
            1884,
            "--died",
            1962,
            "--notes",
            "Family historian",
        )
        self.add_person("Ingrid Jensen", 2)

        self.assertTrue(self.database.is_file())
        people = self.run_cli("list")
        self.assertIn("Søren Jensen", people)
        self.assertIn("Ingrid Jensen", people)

        profile = self.run_cli("show", 1)
        for value in ("Søren Jensen", "1884", "1962", "Family historian"):
            self.assertIn(value, profile)

    def test_person_names_work_as_references_across_commands(self):
        self.add_person("Ulrik Example", 1)
        self.add_person("Ulla Example", 2)
        self.add_person("Child Example", 3)

        self.run_cli("parent", "Ulrik Example", "Child Example", "--type", "biological")
        self.assertIn("Ulrik Example", self.run_cli("show", "Child Example"))
        self.assertIn("Updated", self.run_cli("edit", "Ulrik Example", "--notes", "Named ref"))
        self.assertIn("Ulrik Example", self.run_cli("tree", "Child Example"))
        self.assertIn("50.00%", self.run_cli("distance", "Ulrik Example", "Child Example"))
        self.run_cli("partner", "Ulla Example", "Child Example")
        self.assertIn("Ulla Example", self.run_cli("show", "Child Example"))
        self.run_cli("unlink-partner", "Ulla Example", "Child Example")
        self.run_cli("clear-parents", "Child Example")
        self.assertIn(
            "No recorded shared biological ancestor connects",
            self.run_cli("distance", "Ulrik Example", "Child Example"),
        )

    def test_gender_can_be_added_edited_and_cleared(self):
        self.add_person(
            "Alex Example", 1, "--gender", "non-binary",
            "--gender-source", "Self-description",
        )
        profile = self.run_cli("show", 1)
        self.assertIn("Gender: non-binary", profile)
        self.assertIn("Gender source: Self-description", profile)

        self.run_cli("edit", 1, "--gender", "woman")
        profile = self.run_cli("show", 1)
        self.assertIn("Gender: woman", profile)
        self.assertNotIn("Gender source:", profile)

        self.run_cli("edit", 1, "--gender-source", "Historical record")
        self.assertIn("Gender source: Historical record", self.run_cli("show", 1))
        self.run_cli("edit", 1, "--clear-gender")
        profile = self.run_cli("show", 1)
        self.assertIn("Gender: Not recorded", profile)
        self.assertNotIn("Gender source:", profile)

    def test_short_command_aliases_match_full_commands(self):
        self.add_person("Parent", 1)
        self.add_person("Child", 2)
        self.run_cli("p", "Parent", "Child", "--type", "biological")
        self.assertEqual(self.run_cli("ls"), self.run_cli("list"))
        self.assertEqual(self.run_cli("s", "Child"), self.run_cli("show", "Child"))
        self.assertEqual(self.run_cli("t", "Child"), self.run_cli("tree", "Child"))
        self.assertEqual(
            self.run_cli("rel", "Parent", "Child"),
            self.run_cli("distance", "Parent", "Child"),
        )
        alias_dot = Path(self.temporary_directory.name) / "alias.dot"
        full_dot = Path(self.temporary_directory.name) / "full.dot"
        self.run_cli("dot", alias_dot)
        self.run_cli("export-dot", full_dot)
        self.assertEqual(alias_dot.read_text(), full_dot.read_text())

    def test_tree_alias_accepts_all_option(self):
        self.add_person("Solo", 1)
        self.assertEqual(self.run_cli("t", "--all"), self.run_cli("tree", "--all"))

    def test_person_reference_requires_disambiguation_for_duplicate_names(self):
        self.add_person("Alex", 1)
        self.add_person("Alex", 2)
        error = self.run_cli("show", "Alex", expected_code=1)
        self.assertEqual(error, "")
        self.assertIn("unknown or ambiguous", self.last_stderr)
        self.assertIn("Alex [#2]", self.run_cli("show", "Alex [#2]"))
        self.assertIn("Alex [#1]", self.run_cli("show", 1))

    def test_person_name_completion_returns_matching_labeled_people(self):
        self.add_person("Ulrik", 1)
        self.add_person("Ulla", 2)
        self.add_person("Alex", 3)
        matches = self.run_cli("complete-people", "Ul")
        self.assertEqual(matches.splitlines(), ["Ulla [#2]", "Ulrik [#1]"])

    def test_bash_tab_completion_suggests_name_references(self):
        self.add_person("Ulrik", 1)
        self.add_person("Ulla", 2)
        script = PROJECT_ROOT / "family-tree-completion.bash"
        main_path = MAIN.as_posix()
        result = subprocess.run(
            [
                "bash", "-c",
                f'source "{script}"; COMP_WORDS=(python3 \'"{main_path}"\' show Ul); '
                'COMP_CWORD=3; _family_tree_person_complete; '
                'printf "%s\\n" "${COMPREPLY[@]}"',
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "FAMILY_TREE_DATABASE": str(self.database)},
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [r"Ulla\ \[#2\]", r"Ulrik\ \[#1\]"],
        )

    def test_interactive_new_adds_person_sources_and_biological_parents(self):
        self.add_person("Alex Example", 1)
        self.add_person("Robin Example", 2)
        prompts = "\n".join((
            "Sam Example", "1990-05-04", "2020", "Family notes",
            "woman", "Name record", "Birth record", "Death record", "Self-description",
            "Alex Example", "biological", "Birth certificate",
            "Robin Example", "adoptive", "Adoption record", "",
        )) + "\n"

        result = self.run_cli("new", stdin_text=prompts)

        self.assertIn("Added Sam Example [#3] (b. 1990-05-04, d. 2020).", result)
        self.assertIn("Linked to 2 parent(s).", result)
        profile = self.run_cli("show", 3)
        for detail in (
            "Parents: Alex Example [#1]; Robin Example [#2]",
            "Birth source: Birth record",
            "Death source: Death record",
            "Gender: woman",
            "Gender source: Self-description",
            "Parent link: Alex Example [#1] (biological); source: Birth certificate",
            "Parent link: Robin Example [#2] (adoptive); source: Adoption record",
        ):
            self.assertIn(detail, profile)

    def test_interactive_new_selects_duplicate_names_by_completion_label(self):
        self.add_person("Ulrik", 1)
        self.add_person("Ulrik", 2)
        prompts = "\n".join((
            "New person", "", "", "", "", "",
            "Ulrik [#2]", "biological", "Source for second Ulrik", "",
        )) + "\n"

        self.run_cli("new", stdin_text=prompts)

        profile = self.run_cli("show", 3)
        self.assertIn(
            "Parent link: Ulrik [#2] (biological); source: Source for second Ulrik",
            profile,
        )
        self.assertNotIn("Parent link: Ulrik [#1]", profile)

    def test_interactive_new_rejects_invalid_birth_without_adding_person(self):
        prompts = "\n".join((
            "Sam Example", "1990-02-30", "", "", "", "", "", "",
        )) + "\n"
        self.run_cli("new", stdin_text=prompts, expected_code=1)
        self.assertEqual(self.run_cli("list"), "No people yet. Use the add command to start.\n")

    def test_review_unknown_parent_links_makes_individual_decisions(self):
        for person_id, name in enumerate(("Parent One", "Parent Two", "Child One", "Child Two"), 1):
            self.add_person(name, person_id)
        self.run_cli("parent", 1, 3)
        self.run_cli("parent", 2, 3)
        self.run_cli("parent", 1, 4)

        result = self.run_cli(
            "review-parents",
            stdin_text="b\nBirth record\ns\na\nAdoption papers\n",
        )

        self.assertIn("1 biological, 1 adoptive, 0 kept unknown, 1 skipped", result)
        links = self.run_cli("show", 3)
        self.assertIn("Parent link: Parent One [#1] (biological); source: Birth record", links)
        self.assertIn("Parent link: Parent Two [#2] (unknown)", links)
        self.assertIn(
            "Parent link: Parent One [#1] (adoptive); source: Adoption papers",
            self.run_cli("show", 4),
        )

    def test_review_unknown_parent_links_can_keep_unknown_and_empty_review_is_clear(self):
        self.add_person("Parent", 1)
        self.add_person("Child", 2)
        self.run_cli("parent", 1, 2)
        result = self.run_cli("review-parents", stdin_text="u\n\n")
        self.assertIn("0 biological, 0 adoptive, 1 kept unknown, 0 skipped", result)
        self.run_cli("edit-parent", 1, 2, "--type", "adoptive")
        self.assertIn("No unknown parent relationships to review", self.run_cli("review-parents"))

    def test_review_missing_gender_updates_people_and_skips_individually(self):
        self.add_person("Alex", 1)
        self.add_person("Robin", 2)
        self.add_person("Casey", 3, "--gender", "woman")

        result = self.run_cli(
            "review-gender",
            stdin_text="non-binary\nSelf-description\n\n",
        )

        self.assertIn("1 updated, 1 skipped", result)
        alex = self.run_cli("show", 1)
        self.assertIn("Gender: non-binary", alex)
        self.assertIn("Gender source: Self-description", alex)
        self.assertIn("Gender: Not recorded", self.run_cli("show", 2))
        self.assertIn(
            "1 updated, 0 skipped",
            self.run_cli("review-gender", stdin_text="man\n\n"),
        )
        self.assertIn("No people with gender not recorded to review", self.run_cli("review-gender"))

    def test_review_missing_gender_empty_tree_and_interruption_are_clear(self):
        self.assertIn(
            "No people with gender not recorded to review",
            self.run_cli("review-gender"),
        )
        self.add_person("Alex", 1)
        result = self.run_cli("review-gender", stdin_text="\n")
        self.assertIn("0 updated, 1 skipped", result)
        self.assertIn("Gender: Not recorded", self.run_cli("show", 1))

    def test_export_dot_contains_people_parent_types_and_partner_links(self):
        self.add_person('Alex "Ace" Example', 1, "--notes", "Family note")
        self.add_person("Robin Example", 2)
        self.add_person("Sam Example", 3)
        self.run_cli("parent", 2, 1, "--type", "biological", "--source", "Birth record")
        self.run_cli("partner", 2, 3, "--source", "Marriage record")
        output_path = Path(self.temporary_directory.name) / "family.dot"

        result = self.run_cli("export-dot", output_path)
        dot = output_path.read_text(encoding="utf-8")
        self.assertIn("Graphviz DOT exported", result)
        self.assertIn("digraph family_tree {", dot)
        self.assertIn(r'Alex \"Ace\" Example [#1]', dot)
        self.assertIn('person_2 -> person_1 [label="biological", tooltip="Birth record"]', dot)
        self.assertIn(
            'person_2 -> person_3 [dir=none, style=dashed, label="partners", '
            'constraint=false, tooltip="Marriage record"]',
            dot,
        )
        self.assertIn('tooltip="Family note"', dot)

    def test_profile_shows_parents_children_and_symmetric_partners(self):
        for person_id, name in enumerate(
            ("Edith", "Noor", "Ava", "Leo"), start=1
        ):
            self.add_person(name, person_id)

        self.run_cli("parent", 1, 2)
        self.run_cli("parent", 2, 3)
        self.run_cli("partner", 2, 4)

        profile = self.run_cli("show", 2)
        for name in ("Noor", "Edith", "Ava", "Leo"):
            self.assertIn(name, profile)
        self.assertIn("Noor", self.run_cli("show", 4))

    def test_sources_and_parent_relationship_types_are_recorded_and_editable(self):
        self.add_person(
            "Robin", 1, "--born", 1965, "--died", 2020,
            "--name-source", "Birth register", "--born-source", "Parish record",
            "--died-source", "Cemetery record",
        )
        self.add_person("Alex", 2)
        self.run_cli(
            "parent", 1, 2, "--type", "adoptive", "--source", "Adoption record"
        )
        self.run_cli("partner", 1, 2, "--source", "Marriage record")

        profile = self.run_cli("show", 2)
        for detail in (
            "Parents: Robin [#1] (b. 1965, d. 2020)",
            "Parent link: Robin [#1] (adoptive); source: Adoption record",
        ):
            self.assertIn(detail, profile)
        profile = self.run_cli("show", 1)
        for detail in (
            "Name source: Birth register",
            "Birth source: Parish record",
            "Death source: Cemetery record",
            "Child link: Alex [#2] (adoptive); source: Adoption record",
            "Partner link source (Alex [#2]): Marriage record",
        ):
            self.assertIn(detail, profile)

        self.run_cli(
            "edit-parent", 1, 2, "--type", "biological", "--source", "DNA record"
        )
        self.assertIn("Parent link: Robin [#1] (biological); source: DNA record",
                      self.run_cli("show", 2))
        self.run_cli("edit", 1, "--born-source", "Verified parish extract")
        self.assertIn("Birth source: Verified parish extract", self.run_cli("show", 1))
        self.run_cli("edit-partner", 1, 2, "--source", "Court record")
        self.assertIn(
            "Partner link source (Alex [#2]): Court record",
            self.run_cli("show", 1),
        )

    def test_relatedness_ignores_adoptive_and_unknown_parent_links(self):
        for person_id, name in enumerate(("Ancestor", "Parent", "Child"), start=1):
            self.add_person(name, person_id)
        self.run_cli("parent", 1, 2, "--type", "biological")
        self.run_cli("parent", 2, 3, "--type", "adoptive")

        result = self.run_cli("distance", 1, 3)
        self.assertIn("Estimated coefficient of relatedness: 0.000000 (0%)", result)
        self.assertIn("No recorded shared biological ancestor connects", result)
        self.run_cli("edit-parent", 2, 3, "--type", "unknown")
        self.assertIn(
            "No recorded shared biological ancestor connects",
            self.run_cli("distance", 1, 3),
        )

    def test_distance_uses_shared_ancestors_not_shared_descendants(self):
        names = ("Ancestor", "Parent", "Child", "Partner", "Shared child", "Unrelated")
        for person_id, name in enumerate(names, start=1):
            self.add_person(name, person_id)
        self.run_cli("parent", 1, 2, "--type", "biological")
        self.run_cli("parent", 2, 3, "--type", "biological")
        self.run_cli("partner", 3, 4)
        self.run_cli("parent", 3, 4, 5, "--type", "biological")

        output = self.run_cli("distance", 1, 3)
        self.assertIn("Shortest path: 2 parent-child links", output)
        self.assertIn("Ancestor [#1] -> Parent [#2] -> Child [#3]", output)
        self.assertIn("Estimated coefficient of relatedness: 0.250000 (25.00%)", output)
        reverse = self.run_cli("distance", 3, 1)
        self.assertIn("Shortest path: 2 parent-child links", reverse)
        self.assertIn("Child [#3] -> Parent [#2] -> Ancestor [#1]", reverse)

        self.assertIn(
            "Estimated coefficient of relatedness: 1.000000 (100%)",
            self.run_cli("distance", 3, 3),
        )
        no_path = self.run_cli("distance", 3, 4)
        self.assertIn("Estimated coefficient of relatedness: 0.000000 (0%)", no_path)
        self.assertIn("No recorded shared biological ancestor connects", no_path)
        self.assertIn("Child [#3]", no_path)
        self.assertIn("Partner [#4]", no_path)
        self.assertIn(
            "No recorded shared biological ancestor connects",
            self.run_cli("distance", 1, 6),
        )

    def test_distance_sums_contributions_from_multiple_shared_ancestors(self):
        for person_id, name in enumerate(
            ("Parent A", "Parent B", "Sibling One", "Sibling Two"), start=1
        ):
            self.add_person(name, person_id)
        self.run_cli("parent", 1, 2, 3, "--type", "biological")
        self.run_cli("parent", 1, 2, 4, "--type", "biological")

        result = self.run_cli("distance", 3, 4)
        self.assertIn("Estimated coefficient of relatedness: 0.500000 (50.00%)", result)
        self.assertIn("Parent A [#1]: 0.250000 (1 independent path pair(s))", result)
        self.assertIn("Parent B [#2]: 0.250000 (1 independent path pair(s))", result)

    def test_distance_counts_multiple_independent_routes_to_same_ancestor(self):
        names = (
            "Root", "Left One", "Left Two", "Right One", "Right Two", "Person A", "Person B"
        )
        for person_id, name in enumerate(names, start=1):
            self.add_person(name, person_id)
        for parent_id, child_id in ((1, 2), (1, 3), (1, 4), (1, 5)):
            self.run_cli("parent", parent_id, child_id, "--type", "biological")
        self.run_cli("parent", 2, 3, 6, "--type", "biological")
        self.run_cli("parent", 4, 5, 7, "--type", "biological")

        result = self.run_cli("distance", 6, 7)
        self.assertIn("Estimated coefficient of relatedness: 0.250000 (25.00%)", result)
        self.assertIn("Root [#1]: 0.250000 (4 independent path pair(s))", result)

    def test_distance_rejects_unknown_people(self):
        self.add_person("Alex", 1)
        self.run_cli("distance", 1, 999, expected_code=1)

    def test_both_parents_can_be_linked_with_child_id_last(self):
        for person_id, name in enumerate(("Alex", "Robin", "Sam"), start=1):
            self.add_person(name, person_id)

        output = self.run_cli("parent", 2, 3, 1)
        self.assertIn("Added 2 parent relationships.", output)
        profile = self.run_cli("show", 1)
        self.assertIn("Parents: Robin [#2]; Sam [#3]", profile)
        self.assertIn("Partners: None recorded", self.run_cli("show", 2))
        for parent_id in (2, 3):
            self.assertIn("Children: Alex [#1]", self.run_cli("show", parent_id))
        before = self.run_cli("tree", 1)

        output = self.run_cli("parent", 2, 2, 3, 1)
        self.assertIn("already exist", output)
        self.assertEqual(self.run_cli("tree", 1), before)

    def test_batch_with_existing_parent_adds_only_the_missing_link(self):
        for person_id, name in enumerate(("Alex", "Robin", "Sam"), start=1):
            self.add_person(name, person_id)
        self.run_cli("parent", 2, 1)

        output = self.run_cli("parent", 2, 3, 1)
        self.assertIn("Added 1 parent relationship.", output)
        self.assertIn("Parents: Robin [#2]; Sam [#3]", self.run_cli("show", 1))

    def test_invalid_second_parent_does_not_save_first_link(self):
        for person_id, name in enumerate(("Alex", "Robin", "Sam"), start=1):
            self.add_person(name, person_id)
        self.run_cli("parent", 1, 3)
        before = [self.run_cli("show", person_id) for person_id in (1, 2, 3)]

        for invalid_parent in (999, 1, 3):
            with self.subTest(invalid_parent=invalid_parent):
                self.run_cli("parent", 2, invalid_parent, 1, expected_code=1)
                self.assertEqual(
                    [self.run_cli("show", person_id) for person_id in (1, 2, 3)],
                    before,
                )

    def test_parent_requires_parent_and_child_ids(self):
        for arguments in (("parent",), ("parent", 1)):
            with self.subTest(arguments=arguments):
                self.run_cli(*arguments, expected_code=2)
                self.assertFalse(self.database.exists())
        self.run_cli("parent", "Robin", 1, expected_code=1)
        self.assertTrue(self.database.exists())

    def test_tree_follows_selected_direction_and_depth(self):
        for person_id, name in enumerate(
            ("Edith", "Noor", "Ava", "Finn", "Leo"), start=1
        ):
            self.add_person(name, person_id)
        self.run_cli("parent", 1, 2)
        self.run_cli("parent", 2, 3)
        self.run_cli("parent", 3, 4)
        self.run_cli("partner", 3, 5)

        ancestors = self.run_cli("tree", 3, "--direction", "ancestors")
        for name in ("Ava", "Noor", "Edith"):
            self.assertIn(name, ancestors)
        for name in ("Finn", "Leo"):
            self.assertNotIn(name, ancestors)

        descendants = self.run_cli("tree", 3, "--direction", "descendants")
        for name in ("Ava", "Finn"):
            self.assertIn(name, descendants)
        for name in ("Noor", "Edith", "Leo"):
            self.assertNotIn(name, descendants)

        shallow = self.run_cli(
            "tree", 3, "--direction", "ancestors", "--depth", 1
        )
        self.assertIn("Ava", shallow)
        self.assertIn("Noor", shallow)
        self.assertNotIn("Edith", shallow)

        root_only = self.run_cli("tree", 3, "--depth", 0)
        self.assertIn("Ava", root_only)
        for name in ("Edith", "Noor", "Finn", "Leo"):
            self.assertNotIn(name, root_only)

    def test_tree_all_prints_every_family_and_shared_descendants(self):
        for person_id, name in enumerate(
            ("Alex", "Robin", "Sam", "Solo"), start=1
        ):
            self.add_person(name, person_id)
        self.run_cli("parent", 1, 2, 3)

        entire_tree = self.run_cli("tree", "--all")
        for name in ("Alex", "Robin", "Sam", "Solo"):
            self.assertIn(name, entire_tree)
        self.assertEqual(entire_tree.count("Alex [#1]"), 1)
        self.assertEqual(entire_tree.count("Robin [#2]"), 1)
        self.assertEqual(entire_tree.count("Sam [#3]"), 2)
        self.assertIn("(already shown above)", entire_tree)

    def test_tree_requires_either_person_id_or_all(self):
        self.run_cli("tree", expected_code=2)
        self.assertFalse(self.database.exists())

        self.add_person("Alex", 1)
        self.run_cli("tree", 1, "--all", expected_code=2)

    def test_rejected_cycle_leaves_saved_relationships_unchanged(self):
        for person_id, name in enumerate(("Edith", "Noor", "Ava"), start=1):
            self.add_person(name, person_id)
        self.run_cli("parent", 1, 2)
        self.run_cli("parent", 2, 3)
        before = self.run_cli("tree", 1, "--direction", "descendants")

        self.run_cli("parent", 3, 1, expected_code=1)

        after = self.run_cli("tree", 1, "--direction", "descendants")
        self.assertEqual(after, before)
        youngest = self.run_cli("tree", 3, "--direction", "descendants")
        self.assertIn("Ava", youngest)
        self.assertNotIn("Edith", youngest)
        self.assertNotIn("Noor", youngest)

    def test_clearing_years_preserves_name_notes_and_other_year(self):
        self.add_person(
            "Søren Jensen",
            1,
            "--born",
            1884,
            "--died",
            1962,
            "--notes",
            "Family historian",
        )
        self.run_cli("edit", 1, "--clear-born")
        profile = self.run_cli("show", 1)
        self.assertNotIn("1884", profile)
        for value in ("1962", "Søren Jensen", "Family historian"):
            self.assertIn(value, profile)

        self.run_cli("edit", 1, "--clear-died")
        profile = self.run_cli("show", 1)
        for value in ("1884", "1962"):
            self.assertNotIn(value, profile)
        for value in ("Søren Jensen", "Family historian"):
            self.assertIn(value, profile)

    def test_full_birth_date_is_displayed_and_preserved_by_other_edits(self):
        self.add_person("Alex Example", 1, "--born", "1992-06-15")
        for command in (("list",), ("show", 1), ("tree", 1)):
            with self.subTest(command=command):
                self.assertIn("1992-06-15", self.run_cli(*command))

        for options in (
            ("--notes", "Date checked against family records"),
            ("--name", "Alex Morgan Example"),
            ("--died", 2020),
        ):
            with self.subTest(options=options):
                self.run_cli("edit", 1, *options)
                self.assertIn("1992-06-15", self.run_cli("show", 1))

        profile = self.run_cli("show", 1)
        self.assertIn("Alex Morgan Example", profile)
        self.assertIn("Date checked against family records", profile)
        self.assertIn("2020", profile)

    def test_year_edit_and_clear_birth_remove_full_date_precision(self):
        self.add_person(
            "Alex Example", 1, "--born", "1992-06-15", "--notes", "Family historian"
        )
        self.run_cli("edit", 1, "--born", 1992)
        profile = self.run_cli("show", 1)
        self.assertIn("1992", profile)
        self.assertNotIn("1992-06-15", profile)

        self.run_cli("edit", 1, "--born", "1992-06-15")
        self.assertIn("1992-06-15", self.run_cli("show", 1))
        self.run_cli("edit", 1, "--clear-born")
        profile = self.run_cli("show", 1)
        self.assertNotIn("1992", profile)
        self.assertIn("Alex Example", profile)
        self.assertIn("Family historian", profile)

    def test_invalid_birth_dates_leave_existing_people_unchanged(self):
        self.add_person("Alex Example", 1, "--born", "1992-06-15")
        before_profile = self.run_cli("show", 1)
        before_people = self.run_cli("list")

        for birth_date in ("1991-02-29", "1992-6-15", "15-06-1992"):
            with self.subTest(birth_date=birth_date):
                self.run_cli(
                    "edit", 1, "--name", "Changed Name", "--born", birth_date,
                    expected_code=1,
                )
                self.assertEqual(self.run_cli("show", 1), before_profile)
                self.run_cli(
                    "add", "Invalid Person", "--born", birth_date, expected_code=1
                )
                self.assertEqual(self.run_cli("list"), before_people)

    def test_valid_leap_day_can_be_added_and_edited(self):
        self.add_person("Robin Example", 1, "--born", "2000-02-29")
        self.assertIn("2000-02-29", self.run_cli("show", 1))

        self.run_cli("edit", 1, "--born", "1996-02-29")
        profile = self.run_cli("show", 1)
        self.assertIn("1996-02-29", profile)
        self.assertNotIn("2000-02-29", profile)

    def test_unlink_commands_remove_relationships(self):
        for person_id, name in enumerate(("Edith", "Noor", "Leo"), start=1):
            self.add_person(name, person_id)
        self.run_cli("parent", 1, 2)
        self.run_cli("partner", 2, 3)

        self.run_cli("unlink-parent", 1, 2)
        self.run_cli("unlink-partner", 3, 2)

        profile = self.run_cli("show", 2)
        self.assertIn("Noor", profile)
        self.assertNotIn("Edith", profile)
        self.assertNotIn("Leo", profile)
        self.assertNotIn("Noor", self.run_cli("show", 1))
        self.assertNotIn("Noor", self.run_cli("show", 3))

    def create_family_for_clearing(self):
        for person_id, name in enumerate(
            ("Lena", "Edith", "Noor", "Ava", "Finn", "Rory", "Leo", "Maya", "Sam", "Nico", "Olive"),
            start=1,
        ):
            self.add_person(name, person_id)
        self.run_cli("edit", 4, "--born", "1980-02-29", "--notes", "Family historian")
        for parent_id, child_id in ((2, 4), (3, 4), (2, 8), (4, 5), (9, 5), (5, 6)):
            self.run_cli("parent", parent_id, child_id)
        for first_id, second_id in ((1, 4), (4, 7), (10, 11)):
            self.run_cli("partner", first_id, second_id)

    def assert_clear_count(self, command, expected_count):
        output = self.run_cli(command, 4)
        self.assertRegex(output, rf"\b{expected_count}\b")
        self.assertRegex(output, r"\b4\b")

    def test_clear_parents_updates_both_ends_preserving_other_relationships(self):
        self.create_family_for_clearing()
        people_before = self.run_cli("list")
        child_before = self.run_cli("show", 5)
        partner_before = self.run_cli("show", 1)

        self.assert_clear_count("clear-parents", 2)
        profile = self.run_cli("show", 4)
        for value in ("Ava", "Finn", "Lena", "Leo", "1980-02-29", "Family historian"):
            self.assertIn(value, profile)
        for name in ("Edith", "Noor"):
            self.assertNotIn(name, profile)
        for parent_id in (2, 3):
            self.assertNotIn("Ava", self.run_cli("show", parent_id))
        self.assertIn("Maya", self.run_cli("show", 2))
        self.assertEqual(self.run_cli("show", 5), child_before)
        self.assertEqual(self.run_cli("show", 1), partner_before)
        self.assertEqual(self.run_cli("list"), people_before)
        self.assert_clear_count("clear-parents", 0)
        self.assertEqual(self.run_cli("show", 4), profile)

    def test_clear_children_preserves_coparent_and_grandchild_links(self):
        self.create_family_for_clearing()
        people_before = self.run_cli("list")
        parent_before = self.run_cli("show", 2)
        grandchild_before = self.run_cli("show", 6)

        self.assert_clear_count("clear-children", 1)
        profile = self.run_cli("show", 4)
        self.assertNotIn("Finn", profile)
        for value in ("Ava", "Edith", "Noor", "Lena", "Leo", "1980-02-29", "Family historian"):
            self.assertIn(value, profile)
        child = self.run_cli("show", 5)
        self.assertNotIn("Ava", child)
        self.assertIn("Sam", child)
        self.assertIn("Rory", child)
        self.assertEqual(self.run_cli("show", 2), parent_before)
        self.assertEqual(self.run_cli("show", 6), grandchild_before)
        self.assertEqual(self.run_cli("list"), people_before)
        self.assert_clear_count("clear-children", 0)
        self.assertEqual(self.run_cli("show", 4), profile)

    def test_clear_partners_updates_both_positions_and_keeps_unrelated_couple(self):
        self.create_family_for_clearing()
        people_before = self.run_cli("list")
        unrelated_before = [self.run_cli("show", person_id) for person_id in (10, 11)]
        tree_before = self.run_cli("tree", 4)

        self.assert_clear_count("clear-partners", 2)
        profile = self.run_cli("show", 4)
        for name in ("Lena", "Leo"):
            self.assertNotIn(name, profile)
        for value in ("Ava", "Edith", "Noor", "Finn", "1980-02-29", "Family historian"):
            self.assertIn(value, profile)
        for partner_id in (1, 7):
            self.assertNotIn("Ava", self.run_cli("show", partner_id))
        self.assertEqual([self.run_cli("show", person_id) for person_id in (10, 11)], unrelated_before)
        self.assertEqual(self.run_cli("tree", 4), tree_before)
        self.assertEqual(self.run_cli("list"), people_before)
        self.assert_clear_count("clear-partners", 0)
        self.assertEqual(self.run_cli("show", 4), profile)

    def test_clear_commands_reject_unknown_person_without_changing_data(self):
        self.create_family_for_clearing()
        people_before = self.run_cli("list")
        profile_before = self.run_cli("show", 4)
        for command in ("clear-parents", "clear-children", "clear-partners"):
            with self.subTest(command=command):
                self.run_cli(command, 999, expected_code=1)
                self.assertEqual(self.run_cli("list"), people_before)
                self.assertEqual(self.run_cli("show", 4), profile_before)

    def test_help_does_not_create_database(self):
        self.run_cli("--help")
        self.assertFalse(self.database.exists())

    def test_unknown_person_returns_validation_error(self):
        self.run_cli("show", 999, expected_code=1)

    def test_invalid_command_returns_argument_error_without_database(self):
        self.run_cli("not-a-command", expected_code=2)
        self.assertFalse(self.database.exists())


if __name__ == "__main__":
    unittest.main()
