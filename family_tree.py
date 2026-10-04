"""Store people and family relationships in a local SQLite database."""

from contextlib import contextmanager
from datetime import date
from pathlib import Path
import sqlite3


class FamilyTree:
    """A family tree backed by a database file, with no external dependencies."""

    def __init__(self, database_path):
        if str(database_path) == ":memory:":
            raise ValueError("Use a database file so the family tree can be saved.")
        self.database_path = Path(database_path).expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS people (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    birth_date TEXT,
                    death_year INTEGER,
                    notes TEXT NOT NULL DEFAULT '',
                    name_source TEXT NOT NULL DEFAULT '',
                    birth_source TEXT NOT NULL DEFAULT '',
                    death_source TEXT NOT NULL DEFAULT '',
                    gender TEXT,
                    gender_source TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS parent_links (
                    parent_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
                    child_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
                    relationship_type TEXT NOT NULL DEFAULT 'unknown'
                        CHECK (relationship_type IN ('biological', 'adoptive', 'unknown')),
                    source TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (parent_id, child_id),
                    CHECK (parent_id != child_id)
                );
                CREATE TABLE IF NOT EXISTS partner_links (
                    person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
                    partner_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
                    source TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (person_id, partner_id),
                    CHECK (person_id < partner_id)
                );
                """
            )
            connection.execute("BEGIN IMMEDIATE")
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(people)")}
            if "birth_date" not in columns:
                connection.execute("ALTER TABLE people ADD COLUMN birth_date TEXT")
            if "birth_year" in columns:
                connection.execute(
                    "UPDATE people SET birth_date = CAST(birth_year AS TEXT) "
                    "WHERE birth_date IS NULL AND birth_year IS NOT NULL"
                )
                connection.execute("ALTER TABLE people DROP COLUMN birth_year")
            for column in ("name_source", "birth_source", "death_source"):
                if column not in columns:
                    connection.execute(
                        f"ALTER TABLE people ADD COLUMN {column} TEXT NOT NULL DEFAULT ''"
                    )
            if "gender" not in columns:
                connection.execute("ALTER TABLE people ADD COLUMN gender TEXT")
            if "gender_source" not in columns:
                connection.execute(
                    "ALTER TABLE people ADD COLUMN gender_source TEXT NOT NULL DEFAULT ''"
                )
            for table, definitions in (
                ("parent_links", {
                    "relationship_type": (
                        "TEXT NOT NULL DEFAULT 'unknown' "
                        "CHECK (relationship_type IN ('biological', 'adoptive', 'unknown'))"
                    ),
                    "source": "TEXT NOT NULL DEFAULT ''",
                }),
                ("partner_links", {"source": "TEXT NOT NULL DEFAULT ''"}),
            ):
                link_columns = {
                    row["name"] for row in connection.execute(f"PRAGMA table_info({table})")
                }
                for column, definition in definitions.items():
                    if column not in link_columns:
                        connection.execute(
                            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                        )

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _validate_source(value, label):
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{label} source must be text.")
        return value.strip() if value is not None else None

    @staticmethod
    def _validate_person(
        name, birth_date, death_year, notes, gender,
        name_source, birth_source, death_source, gender_source,
    ):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Name must not be blank.")
        if birth_date is not None:
            if isinstance(birth_date, bool):
                raise ValueError("Birth date must be a year or a valid date in YYYY-MM-DD format.")
            if isinstance(birth_date, int):
                birth_year = birth_date
                if not 1 <= birth_year <= 9999:
                    raise ValueError("Birth date year must be a whole number from 1 to 9999, or empty.")
                birth_date = str(birth_year)
            elif isinstance(birth_date, str) and birth_date.isdecimal():
                birth_year = int(birth_date)
                if not 1 <= birth_year <= 9999:
                    raise ValueError("Birth date year must be a whole number from 1 to 9999, or empty.")
                birth_date = str(birth_year)
            elif isinstance(birth_date, str):
                message = "Birth date must be a year or a valid date in YYYY-MM-DD format."
                try:
                    parsed_date = date.fromisoformat(birth_date)
                except ValueError:
                    raise ValueError(message) from None
                if parsed_date.isoformat() != birth_date:
                    raise ValueError(message)
                birth_year = parsed_date.year
            else:
                raise ValueError("Birth date must be a year or a valid date in YYYY-MM-DD format.")
        else:
            birth_year = None
        if death_year is not None and (
            isinstance(death_year, bool)
            or not isinstance(death_year, int)
            or not 1 <= death_year <= 9999
        ):
            raise ValueError("Death year must be a whole number from 1 to 9999, or empty.")
        if birth_year is not None and death_year is not None and death_year < birth_year:
            raise ValueError("Death year cannot be before birth year.")
        if not isinstance(notes, str):
            raise ValueError("Notes must be text.")
        if gender is not None and not isinstance(gender, str):
            raise ValueError("Gender must be text or empty.")
        if gender is not None:
            gender = gender.strip() or None
        return (
            name.strip(), birth_date, death_year, notes, gender,
            FamilyTree._validate_source(name_source, "Name"),
            FamilyTree._validate_source(birth_source, "Birth"),
            FamilyTree._validate_source(death_source, "Death"),
            FamilyTree._validate_source(gender_source, "Gender"),
        )

    @staticmethod
    def _require_person(connection, person_id):
        person = connection.execute(
            "SELECT id, name, birth_date, death_year, notes, name_source, birth_source, "
            "death_source, gender, gender_source FROM people WHERE id = ?",
            (person_id,),
        ).fetchone()
        if person is None:
            raise ValueError(f"Person {person_id} does not exist.")
        return dict(person)

    def add_person(
        self, name, birth_date=None, death_year=None, notes="", *,
        gender=None, name_source="", birth_source="", death_source="", gender_source="",
    ):
        values = self._validate_person(
            name, birth_date, death_year, notes, gender,
            name_source, birth_source, death_source, gender_source,
        )
        with self._connection() as connection:
            cursor = connection.execute(
                "INSERT INTO people (name, birth_date, death_year, notes, gender, name_source, "
                "birth_source, death_source, gender_source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                values,
            )
            return cursor.lastrowid

    def update_person(
        self, person_id, name, birth_date=None, death_year=None, notes="",
        *, gender=None, name_source=None, birth_source=None, death_source=None,
        gender_source=None,
    ):
        values = self._validate_person(
            name, birth_date, death_year, notes, gender,
            name_source, birth_source, death_source, gender_source,
        )
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE people SET name = ?, birth_date = ?, death_year = ?, notes = ?, "
                "gender = ?, "
                "name_source = COALESCE(?, name_source), "
                "birth_source = COALESCE(?, birth_source), "
                "death_source = COALESCE(?, death_source), "
                "gender_source = COALESCE(?, gender_source) WHERE id = ?",
                (*values, person_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Person {person_id} does not exist.")

    def list_people(self):
        with self._connection() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT id, name, birth_date, death_year, notes, name_source, birth_source, "
                    "death_source, gender, gender_source "
                    "FROM people ORDER BY name COLLATE NOCASE, id"
                )
            ]

    def get_person(self, person_id):
        with self._connection() as connection:
            return self._require_person(connection, person_id)

    @staticmethod
    def _validate_parent_details(relationship_type, source):
        if relationship_type not in ("biological", "adoptive", "unknown"):
            raise ValueError("Parent relationship type must be biological, adoptive, or unknown.")
        return relationship_type, FamilyTree._validate_source(source, "Parent relationship")

    def add_parent(self, parent_id, child_id, relationship_type="unknown", source=""):
        return self.add_parents([parent_id], child_id, relationship_type, source) == 1

    def add_parents(self, parent_ids, child_id, relationship_type="unknown", source=""):
        """Add parents together, returning the number of new links.

        If any relationship is invalid, none of the requested links are saved.
        """
        relationship_type, source = self._validate_parent_details(relationship_type, source)
        parent_ids = list(parent_ids)
        if not parent_ids:
            raise ValueError("Specify at least one parent.")
        if child_id in parent_ids:
            raise ValueError("A person cannot be their own parent.")
        with self._connection() as connection:
            # Keep validation and insertion together, even if two windows are open.
            connection.execute("BEGIN IMMEDIATE")
            self._require_person(connection, child_id)
            added = 0
            for parent_id in parent_ids:
                self._require_person(connection, parent_id)
                creates_cycle = connection.execute(
                    """
                    WITH RECURSIVE descendants(id) AS (
                        SELECT child_id FROM parent_links WHERE parent_id = ?
                        UNION
                        SELECT links.child_id
                        FROM parent_links AS links
                        JOIN descendants ON links.parent_id = descendants.id
                    )
                    SELECT 1 FROM descendants WHERE id = ? LIMIT 1
                    """,
                    (child_id, parent_id),
                ).fetchone()
                if creates_cycle:
                    raise ValueError("This relationship would make someone their own ancestor.")
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO parent_links "
                    "(parent_id, child_id, relationship_type, source) VALUES (?, ?, ?, ?)",
                    (parent_id, child_id, relationship_type, source),
                )
                added += cursor.rowcount
            return added

    def update_parent_link(
        self, parent_id, child_id, relationship_type=None, source=None,
    ):
        if relationship_type is not None and relationship_type not in (
            "biological", "adoptive", "unknown"
        ):
            raise ValueError("Parent relationship type must be biological, adoptive, or unknown.")
        source = self._validate_source(source, "Parent relationship")
        with self._connection() as connection:
            self._require_person(connection, parent_id)
            self._require_person(connection, child_id)
            cursor = connection.execute(
                "UPDATE parent_links SET "
                "relationship_type = COALESCE(?, relationship_type), "
                "source = COALESCE(?, source) WHERE parent_id = ? AND child_id = ?",
                (relationship_type, source, parent_id, child_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Parent relationship {parent_id} -> {child_id} does not exist.")

    def remove_parent(self, parent_id, child_id):
        with self._connection() as connection:
            self._require_person(connection, parent_id)
            self._require_person(connection, child_id)
            connection.execute(
                "DELETE FROM parent_links WHERE parent_id = ? AND child_id = ?",
                (parent_id, child_id),
            )

    def clear_parents(self, person_id):
        """Remove all parents of this person and return the number of links removed."""
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_person(connection, person_id)
            cursor = connection.execute(
                "DELETE FROM parent_links WHERE child_id = ?", (person_id,)
            )
            return cursor.rowcount

    def clear_children(self, person_id):
        """Remove links to this person's direct children and return the link count."""
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_person(connection, person_id)
            cursor = connection.execute(
                "DELETE FROM parent_links WHERE parent_id = ?", (person_id,)
            )
            return cursor.rowcount

    def add_partner(self, person_id, partner_id, source=""):
        if person_id == partner_id:
            raise ValueError("A person cannot be their own partner.")
        source = self._validate_source(source, "Partner relationship")
        with self._connection() as connection:
            self._require_person(connection, person_id)
            self._require_person(connection, partner_id)
            first_id, second_id = sorted((person_id, partner_id))
            cursor = connection.execute(
                "INSERT OR IGNORE INTO partner_links (person_id, partner_id, source) "
                "VALUES (?, ?, ?)",
                (first_id, second_id, source),
            )
            return cursor.rowcount == 1

    def update_partner_link(self, person_id, partner_id, source):
        source = self._validate_source(source, "Partner relationship")
        with self._connection() as connection:
            self._require_person(connection, person_id)
            self._require_person(connection, partner_id)
            first_id, second_id = sorted((person_id, partner_id))
            cursor = connection.execute(
                "UPDATE partner_links SET source = ? WHERE person_id = ? AND partner_id = ?",
                (source, first_id, second_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Partner relationship {person_id} and {partner_id} does not exist.")

    def remove_partner(self, person_id, partner_id):
        with self._connection() as connection:
            self._require_person(connection, person_id)
            self._require_person(connection, partner_id)
            first_id, second_id = sorted((person_id, partner_id))
            connection.execute(
                "DELETE FROM partner_links WHERE person_id = ? AND partner_id = ?",
                (first_id, second_id),
            )

    def clear_partners(self, person_id):
        """Remove all partners of this person and return the number of links removed."""
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_person(connection, person_id)
            cursor = connection.execute(
                "DELETE FROM partner_links WHERE person_id = ? OR partner_id = ?",
                (person_id, person_id),
            )
            return cursor.rowcount

    def list_parent_links(self):
        with self._connection() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT parent_id, child_id, relationship_type, source "
                    "FROM parent_links ORDER BY parent_id, child_id"
                )
            ]

    def list_partner_links(self):
        with self._connection() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT person_id, partner_id, source "
                    "FROM partner_links ORDER BY person_id, partner_id"
                )
            ]
