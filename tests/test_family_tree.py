"""Check persistence and relationship rules using disposable databases."""

from pathlib import Path
import sqlite3
import tempfile
import unittest

from family_tree import FamilyTree


class FamilyTreeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "data" / "family.db"
        self.tree = FamilyTree(self.path)

    def test_people_and_relationships_persist(self):
        parent = self.tree.add_person("  Søren O'Neill  ", 1960, None, "Family notes")
        child = self.tree.add_person("Lærke", 1990)
        partner = self.tree.add_person("Alex", 1962, 2020)
        self.tree.add_parent(parent, child)
        self.tree.add_partner(parent, partner)

        reopened = FamilyTree(self.path)
        self.assertEqual(
            reopened.get_person(parent),
            {
                "id": parent,
                "name": "Søren O'Neill",
                "birth_date": "1960",
                "death_year": None,
                "notes": "Family notes",
                "name_source": "",
                "birth_source": "",
                "death_source": "",
                "gender": None,
                "gender_source": "",
            },
        )
        self.assertEqual(reopened.list_parent_links(), [{
            "parent_id": parent, "child_id": child, "relationship_type": "unknown", "source": "",
        }])
        self.assertEqual(reopened.list_partner_links(), [{
            "person_id": parent, "partner_id": partner, "source": "",
        }])

    def test_fact_and_relationship_sources_persist_and_can_be_updated(self):
        parent = self.tree.add_person(
            "Parent", 1960, notes="Notes",
            name_source="Identity card", birth_source="Birth record",
            death_source="Death record", gender="  woman  ",
            gender_source="Self-description",
        )
        child = self.tree.add_person("Child")
        self.tree.add_parent(parent, child, "biological", "Birth record")
        self.tree.add_partner(parent, child, "Marriage record")

        self.tree.update_person(
            parent, "Parent", gender="non-binary",
            name_source="Verified identity", gender_source="Verified interview",
        )
        self.tree.update_parent_link(parent, child, "adoptive", "Adoption record")
        self.tree.update_partner_link(parent, child, "")

        reopened = FamilyTree(self.path)
        person = reopened.get_person(parent)
        self.assertEqual(person["name_source"], "Verified identity")
        self.assertEqual(person["birth_source"], "Birth record")
        self.assertEqual(person["death_source"], "Death record")
        self.assertEqual(person["gender"], "non-binary")
        self.assertEqual(person["gender_source"], "Verified interview")
        self.assertEqual(reopened.list_parent_links(), [{
            "parent_id": parent, "child_id": child,
            "relationship_type": "adoptive", "source": "Adoption record",
        }])
        self.assertEqual(reopened.list_partner_links(), [{
            "person_id": parent, "partner_id": child, "source": "",
        }])

    def test_invalid_parent_type_and_source_are_rejected(self):
        parent = self.tree.add_person("Parent")
        child = self.tree.add_person("Child")
        with self.assertRaisesRegex(ValueError, "type must be"):
            self.tree.add_parent(parent, child, "foster")
        with self.assertRaisesRegex(ValueError, "source must be text"):
            self.tree.add_parent(parent, child, source=12)
        with self.assertRaisesRegex(ValueError, "source must be text"):
            self.tree.add_person("Invalid", name_source=12)
        self.assertEqual(self.tree.list_parent_links(), [])

    def test_duplicate_names_have_distinct_ids_and_list_is_sorted(self):
        last = self.tree.add_person("Zoe")
        first = self.tree.add_person("Alex")
        second = self.tree.add_person("Alex")
        self.assertNotEqual(first, second)
        self.assertEqual([person["id"] for person in self.tree.list_people()], [first, second, last])

    def test_birth_date_or_year_persists_as_single_value(self):
        person = self.tree.add_person("Robin", birth_date="2000-02-29")
        reopened = FamilyTree(self.path)
        self.assertEqual(reopened.get_person(person)["birth_date"], "2000-02-29")
        self.assertEqual(reopened.list_people(), [reopened.get_person(person)])
        year = self.tree.add_person("Alex", 1980)
        self.assertEqual(self.tree.get_person(year)["birth_date"], "1980")

    def test_invalid_birth_dates_do_not_insert(self):
        invalid_dates = [
            "", " ", "2001-02-29", "1900-02-29", "2000-04-31", "2000-13-01",
            "2000-00-01", "2000-01-00", "0000-01-01", "10000-01-01",
            "2000-2-09", "2000-02-9", "29/02/2000", "20000229", "2000-W09-2",
            "2000-02-29T12:00:00", " 2000-02-29", "2000-02-29 ", 20000229, True,
        ]
        for birth_date in invalid_dates:
            with self.subTest(birth_date=birth_date), self.assertRaisesRegex(ValueError, "Birth date"):
                self.tree.add_person("Alex", birth_date=birth_date)
        self.assertEqual(self.tree.list_people(), [])

    def test_birth_date_year_must_precede_death_year(self):
        with self.assertRaisesRegex(ValueError, "Death year cannot"):
            self.tree.add_person("Robin", death_year=1979, birth_date="1980-01-01")
        self.assertEqual(self.tree.list_people(), [])
        person = self.tree.add_person("Robin", death_year=1980, birth_date="1980-01-01")
        self.assertEqual(self.tree.get_person(person)["death_year"], 1980)

    def test_birth_date_can_be_updated_and_replaced_with_year(self):
        person = self.tree.add_person("Alex", 1980)
        self.tree.update_person(person, "Alex", birth_date="1981-03-04")
        self.assertEqual(self.tree.get_person(person)["birth_date"], "1981-03-04")
        self.tree.update_person(person, "Alex", 1982)
        self.assertEqual(self.tree.get_person(person)["birth_date"], "1982")

    def test_invalid_birth_date_edit_preserves_original_person(self):
        person = self.tree.add_person("Alex", notes="Keep this", birth_date="1980-02-29")
        before = self.tree.get_person(person)
        changes = [
            {"birth_date": "1981-02-29"},
            {"death_year": 1979, "birth_date": "1980-02-29"},
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.tree.update_person(person, "Changed", notes="Discard this", **change)
            self.assertEqual(self.tree.get_person(person), before)

    def test_existing_database_migrates_without_losing_people_or_links(self):
        old_path = Path(self.directory.name) / "old-family.db"
        connection = sqlite3.connect(old_path)
        try:
            connection.executescript(
                """
                CREATE TABLE people (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    birth_year INTEGER,
                    death_year INTEGER,
                    notes TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE parent_links (
                    parent_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
                    child_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
                    PRIMARY KEY (parent_id, child_id),
                    CHECK (parent_id != child_id)
                );
                CREATE TABLE partner_links (
                    person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
                    partner_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
                    PRIMARY KEY (person_id, partner_id),
                    CHECK (person_id < partner_id)
                );
                INSERT INTO people VALUES (7, 'Alex', 1950, 2020, 'Keep original notes');
                INSERT INTO people VALUES (12, 'Robin', 1980, NULL, '');
                INSERT INTO people VALUES (18, 'Charlie', NULL, NULL, 'Unknown birthday');
                INSERT INTO parent_links VALUES (7, 12);
                INSERT INTO partner_links VALUES (7, 18);
                """
            )
        finally:
            connection.close()

        for attempt in range(2):
            with self.subTest(attempt=attempt):
                migrated = FamilyTree(old_path)
                self.assertEqual(migrated.get_person(7), {
                    "id": 7, "name": "Alex", "birth_date": "1950", "death_year": 2020,
                    "notes": "Keep original notes",
                    "name_source": "", "birth_source": "", "death_source": "",
                    "gender": None, "gender_source": "",
                })
                self.assertEqual(len(migrated.list_people()), 3)
                self.assertIsNone(migrated.get_person(18)["birth_date"])
                with sqlite3.connect(old_path) as connection:
                    columns = {row[1] for row in connection.execute("PRAGMA table_info(people)")}
                self.assertNotIn("birth_year", columns)
                self.assertEqual(migrated.list_parent_links(), [{
                    "parent_id": 7, "child_id": 12,
                    "relationship_type": "unknown", "source": "",
                }])
                self.assertEqual(migrated.list_partner_links(), [{
                    "person_id": 7, "partner_id": 18, "source": "",
                }])

        migrated.update_person(12, "Robin", birth_date="1980-02-29")
        self.assertEqual(FamilyTree(old_path).get_person(12)["birth_date"], "1980-02-29")
        with self.assertRaisesRegex(ValueError, "own ancestor"):
            migrated.add_parent(12, 7)

    def test_existing_database_merges_two_birth_columns_before_removing_year(self):
        old_path = Path(self.directory.name) / "two-birth-columns.db"
        connection = sqlite3.connect(old_path)
        try:
            connection.executescript(
                """
                CREATE TABLE people (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    birth_year INTEGER,
                    birth_date TEXT,
                    death_year INTEGER,
                    notes TEXT NOT NULL DEFAULT ''
                );
                INSERT INTO people VALUES (1, 'Year only', 1884, NULL, NULL, '');
                INSERT INTO people VALUES (2, 'Full date', 1992, '1992-06-15', NULL, '');
                """
            )
        finally:
            connection.close()

        migrated = FamilyTree(old_path)
        self.assertEqual(migrated.get_person(1)["birth_date"], "1884")
        self.assertEqual(migrated.get_person(2)["birth_date"], "1992-06-15")
        with sqlite3.connect(old_path) as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(people)")}
        self.assertNotIn("birth_year", columns)

    def test_invalid_person_details_do_not_insert(self):
        invalid_people = [
            {"name": "   "},
            {"name": None},
            {"name": "Alex", "birth_date": 0},
            {"name": "Alex", "birth_date": 10000},
            {"name": "Alex", "birth_date": True},
            {"name": "Alex", "birth_date": 2000.5},
            {"name": "Alex", "birth_date": "10000"},
            {"name": "Alex", "birth_date": "20oo"},
            {"name": "Alex", "death_year": False},
            {"name": "Alex", "death_year": -1},
            {"name": "Alex", "birth_date": "2000", "death_year": 1999},
            {"name": "Alex", "notes": None},
            {"name": "Alex", "gender": 4},
        ]
        for person in invalid_people:
            with self.subTest(person=person), self.assertRaises(ValueError):
                self.tree.add_person(**person)
        self.assertEqual(self.tree.list_people(), [])

    def test_gender_is_optional_free_text_and_blank_values_are_unknown(self):
        person = self.tree.add_person("Alex", gender="   ")
        self.assertIsNone(self.tree.get_person(person)["gender"])
        with self.assertRaisesRegex(ValueError, "Gender source must be text"):
            self.tree.add_person("Invalid", gender_source=12)
        self.assertEqual(len(self.tree.list_people()), 1)

    def test_valid_year_boundaries_and_unknown_birth(self):
        ancient = self.tree.add_person("Ancient", 1, 1)
        future = self.tree.add_person("Future", None, 9999)
        self.assertEqual(self.tree.get_person(ancient)["birth_date"], "1")
        self.assertIsNone(self.tree.get_person(future)["birth_date"])

    def test_edit_changes_person_and_preserves_links(self):
        parent = self.tree.add_person("Alex")
        child = self.tree.add_person("Robin")
        self.tree.add_parent(parent, child)
        self.tree.update_person(parent, "  Alexandra  ", 1970, 2025, "Updated notes")
        self.assertEqual(self.tree.get_person(parent)["name"], "Alexandra")
        self.assertEqual(self.tree.get_person(parent)["death_year"], 2025)
        self.assertEqual(self.tree.get_person(parent)["notes"], "Updated notes")
        self.assertEqual(self.tree.list_parent_links(), [{
            "parent_id": parent, "child_id": child,
            "relationship_type": "unknown", "source": "",
        }])
        self.tree.update_person(parent, "Alexandra")
        self.assertIsNone(self.tree.get_person(parent)["birth_date"])

    def test_invalid_edit_preserves_previous_person(self):
        person = self.tree.add_person("Alex", 1980, None, "Keep this")
        before = self.tree.get_person(person)
        with self.assertRaisesRegex(ValueError, "Death year"):
            self.tree.update_person(person, "Changed", 1980, 1970, "Discard this")
        self.assertEqual(self.tree.get_person(person), before)

    def test_missing_people_raise_clear_errors(self):
        person = self.tree.add_person("Alex")
        operations = [
            lambda: self.tree.get_person(999),
            lambda: self.tree.update_person(999, "Missing"),
            lambda: self.tree.add_parent(person, 999),
            lambda: self.tree.add_parent(999, person),
            lambda: self.tree.add_partner(person, 999),
            lambda: self.tree.add_partner(999, person),
            lambda: self.tree.remove_parent(person, 999),
            lambda: self.tree.remove_partner(999, person),
        ]
        for operation in operations:
            with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, "does not exist"):
                operation()
        self.assertEqual(self.tree.list_parent_links(), [])
        self.assertEqual(self.tree.list_partner_links(), [])

    def test_self_relationships_are_rejected(self):
        person = self.tree.add_person("Alex")
        with self.assertRaisesRegex(ValueError, "own parent"):
            self.tree.add_parent(person, person)
        with self.assertRaisesRegex(ValueError, "own partner"):
            self.tree.add_partner(person, person)

    def test_parent_cycles_are_rejected_without_changing_links(self):
        people = [self.tree.add_person(f"Generation {i}") for i in range(8)]
        for parent, child in zip(people, people[1:]):
            self.tree.add_parent(parent, child)
        before = self.tree.list_parent_links()
        with self.assertRaisesRegex(ValueError, "own ancestor"):
            self.tree.add_parent(people[1], people[0])
        with self.assertRaisesRegex(ValueError, "own ancestor"):
            self.tree.add_parent(people[-1], people[0])
        self.assertEqual(self.tree.list_parent_links(), before)

    def test_more_than_two_parents_and_shared_ancestors_are_allowed(self):
        ancestor, left, right, extra, child = [self.tree.add_person(name) for name in (
            "Ancestor", "Left", "Right", "Extra", "Child"
        )]
        for parent, descendant in (
            (ancestor, left), (ancestor, right), (left, child), (right, child), (extra, child)
        ):
            self.assertTrue(self.tree.add_parent(parent, descendant))
        self.assertEqual(len(self.tree.list_parent_links()), 5)
        with self.assertRaisesRegex(ValueError, "own ancestor"):
            self.tree.add_parent(child, ancestor)

    def test_duplicate_parent_links_and_removal(self):
        parent = self.tree.add_person("Parent")
        child = self.tree.add_person("Child")
        self.assertTrue(self.tree.add_parent(parent, child))
        self.assertFalse(self.tree.add_parent(parent, child))
        self.assertEqual(len(self.tree.list_parent_links()), 1)
        self.tree.remove_parent(parent, child)
        self.tree.remove_parent(parent, child)
        self.assertEqual(self.tree.list_parent_links(), [])
        self.assertTrue(self.tree.add_parent(child, parent))

    def test_parent_batch_persists_and_allows_more_than_two_parents(self):
        parents = [self.tree.add_person(name) for name in ("Alex", "Robin", "Charlie")]
        child = self.tree.add_person("Jamie")
        self.assertEqual(self.tree.add_parents(iter(parents), child), 3)
        self.assertEqual(FamilyTree(self.path).list_parent_links(), [
            {"parent_id": parent, "child_id": child,
             "relationship_type": "unknown", "source": ""} for parent in parents
        ])

    def test_parent_batch_counts_only_new_distinct_links(self):
        first = self.tree.add_person("First parent")
        second = self.tree.add_person("Second parent")
        child = self.tree.add_person("Child")
        self.assertIs(self.tree.add_parent(first, child), True)
        self.assertEqual(self.tree.add_parents([first, second, first, second], child), 1)
        self.assertEqual(self.tree.add_parents([second, first], child), 0)
        self.assertIs(self.tree.add_parent(second, child), False)
        self.assertEqual(self.tree.list_parent_links(), [
            {"parent_id": first, "child_id": child, "relationship_type": "unknown", "source": ""},
            {"parent_id": second, "child_id": child, "relationship_type": "unknown", "source": ""},
        ])

    def test_invalid_second_parent_keeps_all_existing_data_and_no_new_links(self):
        existing = self.tree.add_person("Existing parent", 1960, notes="Keep these notes")
        candidate = self.tree.add_person("New parent", birth_date="1960-02-29")
        child = self.tree.add_person("Child", 1990)
        descendant = self.tree.add_person("Descendant", 2020)
        self.tree.add_parent(existing, child)
        self.tree.add_parent(child, descendant)
        self.tree.add_partner(existing, candidate)
        original_people = self.tree.list_people()
        original_links = self.tree.list_parent_links()
        original_partners = self.tree.list_partner_links()

        for invalid_parent, message in (
            (999, "does not exist"),
            (child, "own parent"),
            (descendant, "own ancestor"),
        ):
            with self.subTest(invalid_parent=invalid_parent):
                with self.assertRaisesRegex(ValueError, message):
                    self.tree.add_parents([candidate, invalid_parent], child)
                reopened = FamilyTree(self.path)
                self.assertEqual(reopened.list_parent_links(), original_links)
                self.assertEqual(reopened.list_people(), original_people)
                self.assertEqual(reopened.list_partner_links(), original_partners)

    def test_empty_parent_batch_and_missing_child_are_rejected(self):
        first = self.tree.add_person("First parent")
        second = self.tree.add_person("Second parent")
        child = self.tree.add_person("Child")
        with self.assertRaisesRegex(ValueError, "at least one parent"):
            self.tree.add_parents(iter(()), child)
        with self.assertRaisesRegex(ValueError, "Person 999 does not exist"):
            self.tree.add_parents([first, second], 999)
        self.assertEqual(self.tree.list_parent_links(), [])

    def test_partners_are_unordered_allow_multiple_and_can_be_removed(self):
        first = self.tree.add_person("Alex")
        second = self.tree.add_person("Robin")
        third = self.tree.add_person("Charlie")
        self.assertTrue(self.tree.add_partner(second, first))
        self.assertFalse(self.tree.add_partner(first, second))
        self.assertFalse(self.tree.add_partner(second, first))
        self.assertTrue(self.tree.add_partner(first, third))
        self.assertEqual(self.tree.list_partner_links(), [
            {"person_id": first, "partner_id": second, "source": ""},
            {"person_id": first, "partner_id": third, "source": ""},
        ])
        self.tree.remove_partner(second, first)
        self.tree.remove_partner(first, second)
        self.assertEqual(self.tree.list_partner_links(), [
            {"person_id": first, "partner_id": third, "source": ""},
        ])

    def create_family_for_clearing(self):
        names = (
            "First parent", "Second parent", "Earlier partner", "Focus person",
            "First child", "Second child", "Grandchild", "Sibling", "Co-parent",
            "Later partner", "Unrelated person", "Unrelated partner",
        )
        people = {
            name: self.tree.add_person(name, notes=f"Notes for {name}")
            for name in names
        }
        focus = people["Focus person"]
        self.tree.update_person(focus, "Focus person", notes="Keep these notes", birth_date="1980-02-29")
        for parent, child in (
            ("First parent", "Focus person"),
            ("Second parent", "Focus person"),
            ("First parent", "Sibling"),
            ("Second parent", "Sibling"),
            ("Focus person", "First child"),
            ("Focus person", "Second child"),
            ("Co-parent", "First child"),
            ("First child", "Grandchild"),
        ):
            self.tree.add_parent(people[parent], people[child])
        for first, second in (
            ("Earlier partner", "Focus person"),
            ("Focus person", "Later partner"),
            ("First parent", "Second parent"),
            ("Unrelated person", "Unrelated partner"),
        ):
            self.tree.add_partner(people[first], people[second])
        return people

    def test_clear_parents_keeps_children_siblings_partners_and_details(self):
        people = self.create_family_for_clearing()
        focus = people["Focus person"]
        original_people = self.tree.list_people()
        original_partners = self.tree.list_partner_links()
        removed_parents = {people["First parent"], people["Second parent"]}
        remaining_links = [
            link for link in self.tree.list_parent_links()
            if not (link["child_id"] == focus and link["parent_id"] in removed_parents)
        ]

        self.assertEqual(self.tree.clear_parents(focus), 2)
        reopened = FamilyTree(self.path)
        self.assertEqual(reopened.list_parent_links(), remaining_links)
        self.assertEqual(reopened.list_partner_links(), original_partners)
        self.assertEqual(reopened.list_people(), original_people)
        self.assertEqual(reopened.clear_parents(focus), 0)
        self.assertEqual(reopened.list_parent_links(), remaining_links)

    def test_clear_children_keeps_grandchildren_coparents_and_other_links(self):
        people = self.create_family_for_clearing()
        focus = people["Focus person"]
        original_people = self.tree.list_people()
        original_partners = self.tree.list_partner_links()
        removed_children = {people["First child"], people["Second child"]}
        remaining_links = [
            link for link in self.tree.list_parent_links()
            if not (link["parent_id"] == focus and link["child_id"] in removed_children)
        ]

        self.assertEqual(self.tree.clear_children(focus), 2)
        reopened = FamilyTree(self.path)
        self.assertEqual(reopened.list_parent_links(), remaining_links)
        self.assertEqual(reopened.list_partner_links(), original_partners)
        self.assertEqual(reopened.list_people(), original_people)
        self.assertEqual(reopened.clear_children(focus), 0)
        self.assertEqual(reopened.list_parent_links(), remaining_links)

    def test_clear_partners_removes_both_endpoint_positions_only(self):
        people = self.create_family_for_clearing()
        focus = people["Focus person"]
        original_people = self.tree.list_people()
        original_parents = self.tree.list_parent_links()
        removed_partners = {people["Earlier partner"], people["Later partner"]}
        remaining_links = [
            link for link in self.tree.list_partner_links()
            if focus not in (link["person_id"], link["partner_id"])
            or not removed_partners.intersection((link["person_id"], link["partner_id"]))
        ]

        self.assertEqual(self.tree.clear_partners(focus), 2)
        reopened = FamilyTree(self.path)
        self.assertEqual(reopened.list_partner_links(), remaining_links)
        self.assertEqual(reopened.list_parent_links(), original_parents)
        self.assertEqual(reopened.list_people(), original_people)
        self.assertEqual(reopened.clear_partners(focus), 0)
        self.assertEqual(reopened.list_partner_links(), remaining_links)

    def test_clearing_unknown_person_preserves_all_existing_data(self):
        self.create_family_for_clearing()
        original_people = self.tree.list_people()
        original_parents = self.tree.list_parent_links()
        original_partners = self.tree.list_partner_links()
        for method in (self.tree.clear_parents, self.tree.clear_children, self.tree.clear_partners):
            with self.subTest(method=method.__name__):
                with self.assertRaises(ValueError):
                    method(999)
                self.assertEqual(self.tree.list_people(), original_people)
                self.assertEqual(self.tree.list_parent_links(), original_parents)
                self.assertEqual(self.tree.list_partner_links(), original_partners)


if __name__ == "__main__":
    unittest.main()
