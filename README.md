# Family Tree

A small Python project for building and exploring a family tree in the terminal.
People and relationships are stored locally in SQLite. It uses only the Python
standard library.

## Start

Run commands from the `family-tree` directory:

```bash
python3 main.py --help
python3 main.py list
python3 main.py new
```

The database is created at `data/family_tree.db` when you first run a command.
No package installation or bank-project environment is needed.

## Short command aliases

Full command names remain available. These aliases are convenient for frequent
commands:

| Command | Alias |
|---|---|
| `add` | `a` |
| `new` | `n` |
| `list` | `ls` |
| `show` | `s` |
| `distance` | `rel` |
| `edit` | `e` |
| `parent` | `p` |
| `edit-parent` | `ep` |
| `unlink-parent` | `up` |
| `partner` | `pair` |
| `unlink-partner` | `unpair` |
| `edit-partner` | `epair` |
| `tree` | `t` |
| `review-parents` | `review` |
| `export-dot` | `dot` |
| `clear-parents` | `cp` |
| `clear-children` | `cc` |
| `clear-partners` | `cpartners` |

For example, `python3 main.py ls` lists people and `python3 main.py p 2 1`
links person 2 as a parent of person 1. Run `python3 main.py --help` for the
available commands and options.

## Refer to people by name

Every command that takes a person ID also accepts an exact name, case-insensitively,
or a numeric ID. Names containing spaces should be quoted, for example:

```bash
python3 main.py show "Ulrik Example"
python3 main.py distance "Ulrik Example" "Ulla Example"
python3 main.py parent "Ulrik Example" "Child Example" --type biological
```

If a name is not unique, use the displayed `Name [#ID]` form, such as
`"Alex [#2]"`. To cycle through name suggestions with Tab in Bash, source the
completion script once per shell:

```bash
source ./family-tree-completion.bash
python3 main.py show Ul<Tab>
```

Completion also works for the other commands' person references. Set
`FAMILY_TREE_DATABASE` if the CLI is using a non-default database.

## Add people

```bash
python3 main.py add "Alex Example" --born 1990
python3 main.py add "Robin Example" --born 1965 --born-source "Parish register"
python3 main.py add "Sam Example" --born 1963 --notes "Birth year needs checking" \
  --born-source "Family Bible"
python3 main.py add "Casey Example" --gender "non-binary" \
  --gender-source "Self-description"
```

Each person gets a numeric ID, printed when they are added. Use `list` to find
IDs later. People can have the same name; their IDs keep them separate.
Birth details and death years are optional. Use `--born YEAR` when you know only
the year, or `--born YYYY-MM-DD` for a full birth date. Omit the option when unknown.
Both formats are stored in the same `birth_date` field.
Gender is optional free text, not a fixed category, and may be left unknown.
Use `--gender-source` to record where the description came from.

For a guided entry, run `python3 main.py new`. It prompts for the person's
details, optional sources, and optional existing parents. It also asks for an
optional gender or self-description. Press Enter to skip optional fields. For
each selected parent, it separately asks for the relationship type and source.
The existing `add` command remains available for quick scripted entry.

## Link relatives

For a new database, the example people above have IDs 1, 2, and 3. Substitute your
own IDs if you have already added people.

```bash
# Link Robin and Sam as Alex's biological parents. The child's ID comes last.
python3 main.py parent 2 3 1 --type biological --source "Birth certificate"

# Robin and Sam are partners.
python3 main.py partner 2 3
```

Use `parent PARENT_ID [PARENT_ID ...] CHILD_ID` to link one or more existing
people as parents. A single parent still works: `python3 main.py parent 2 1`.
If any requested link is invalid, the whole command is cancelled. Repeating
an existing link leaves it unchanged.

Parent links have a direction; partner links work both ways. The app allows
multiple parents and partners without assuming gender or marital status.
It rejects self-links and parent relationships that would create an ancestry cycle.
Parent links can be marked `biological`, `adoptive`, or `unknown` (the default).
The `--type` and `--source` options apply to every parent link created by one
`parent` command.
Use `edit-parent PARENT_ID CHILD_ID --type ...` to classify an existing link.
Use `--source` when creating a parent or partner link, or `edit-parent` /
`edit-partner` to update an existing link. `show PERSON_ID` displays the link
types and recorded sources.
To review every relationship still marked unknown, run
`python3 main.py review-parents`. For each parent-child link, choose biological,
adoptive, keep unknown, or skip. Decisions are saved as you go; Ctrl+C stops the
review without discarding decisions already made.
To review people whose gender is not recorded, run
`python3 main.py review-gender`. Enter a free-text gender or self-description and
an optional source for each person, or leave the gender blank to skip them.
Updates are saved as you go.

Add `--name-source`, `--born-source`, and `--died-source` to `add` or `edit` to
record where each detail came from. Source values are free text; pass an empty
string to clear one. Changing a name, birth, or death detail clears its old
source unless a replacement source is supplied.

## Explore the tree

```bash
python3 main.py list
python3 main.py show 1
python3 main.py tree 1
python3 main.py tree 2 --direction descendants --depth 3
python3 main.py tree --all
python3 main.py distance 1 3
python3 main.py export-dot family_tree.dot
```

`tree` shows ancestors by default. With the example above:

```text
Alex Example [#1] (b. 1990)
├── Robin Example [#2] (b. 1965)
└── Sam Example [#3] (b. 1963)
```

`--depth` controls how many generations are shown, from 0 to 20 (default: 4).
Tree views follow parent links. Use `show` to see parents, children, partners,
and notes together. An ancestor shared by multiple branches can appear more
than once in the printed tree.

Use `tree --all` to print every family from its oldest recorded generation,
including people with no recorded relatives. Each person is expanded only once;
later links to the same person are marked as already shown.

Export the whole database as a Graphviz DOT file with `export-dot OUTPUT.dot`.
People are nodes, parent relationships are labeled directed edges, and partner
relationships are dashed undirected edges. Notes and source citations are
included as Graphviz tooltips. The export itself needs no extra Python packages.
If Graphviz is installed, render the file to SVG with:

```bash
dot -Tsvg family_tree.dot -o family_tree.svg
```

`distance PERSON_ID PERSON_ID` estimates the coefficient of relatedness using
all independent parentage paths through shared ancestors. Each shared-ancestor
contribution and the shortest path are shown; a parent-child link contributes
one half along each path. Co-parents are not connected through a shared child,
and partner links are ignored.

This estimate uses only links explicitly marked biological. Adoptive and
unknown links are excluded, and unrecorded ancestry is treated as unrelated.
If there is no connection using explicitly biological links, the command reports
zero and notes that adoptive and unknown links are excluded. The estimate still
depends on accurate records and is not a DNA test or a substitute for verified
genetic data.

## Correct details

```bash
python3 main.py edit 1 --name "Alex Morgan Example" --born 1991
python3 main.py edit 1 --born 1991-06-15
python3 main.py edit 1 --notes "Checked against family records"
python3 main.py edit 1 --clear-born
python3 main.py edit 1 --notes ""
python3 main.py edit 1 --gender "woman"
python3 main.py edit 1 --clear-gender
```

Edits preserve fields you do not specify. Use `--died YEAR` to record a death
year, or `--clear-died` to remove it. Years must be between 1 and 9999; a death
year cannot precede the same person's birth year.

Full birth dates must be valid calendar dates in `YYYY-MM-DD` format. Birth years
and full dates appear in `list`, `show`, and `tree`. Setting `--born YEAR`
replaces a full date with just the year; `--clear-born` removes the birth value.
Editing a name or notes preserves it.
Gender is displayed in `show` and can be changed with `--gender` or removed with
`--clear-gender`; both options are independent of parent and partner links.

## Remove relationships

To remove one link, supply both people's IDs:

```bash
python3 main.py unlink-parent 3 1
python3 main.py unlink-partner 2 3
```

To clear a type of relationship for one person, use their ID:

```bash
python3 main.py clear-parents 1
python3 main.py clear-children 1
python3 main.py clear-partners 1
```

Each command removes the selected links and reports how many were removed.
People, dates, and notes remain saved. Removing a link updates both people's
profiles. `clear-children` removes links to direct children; those children's
links to other parents and their own children are preserved.

## Storage and backups

The database stays beside the project under `data/`, regardless of the terminal's
working directory. To use a different database, put `--database` before the command:

```bash
python3 main.py --database data/practice.db add "Practice Person"
python3 main.py --database data/practice.db list
```

Keep a backup by copying `data/family_tree.db` while no command is running.
Database files and the `data/` folder are excluded from Git. A code commit does
not back up your family data.

Existing databases are migrated automatically on the next command. Recorded
years are moved into the single birth field, full dates are preserved, and old
parent links are classified as unknown rather than assumed biological. Existing
people, relationships, and other details are preserved.

## Project layout

| File | Purpose |
|---|---|
| `main.py` | Terminal commands and tree display |
| `family_tree.py` | People, relationships, validation, and SQLite storage |
| `tests/` | Tests using temporary databases and fictional people |

This version records names, optional gender descriptions, birth years or full
birth dates in one field, death years, notes, parent-link types, and free-text
sources for facts and links.
Full death dates and GEDCOM import/export can be added later.

## Tests

```bash
python3 -m unittest discover -s tests -v
```
