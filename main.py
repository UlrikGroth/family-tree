"""A small command-line interface for a family tree stored in SQLite."""

import argparse
import json
from pathlib import Path
import sqlite3
import sys

try:
    import readline
except ImportError:
    readline = None

from family_tree import FamilyTree


DEFAULT_DATABASE = Path(__file__).resolve().parent / "data" / "family_tree.db"

COMMAND_ALIASES = {
    "a": "add",
    "n": "new",
    "ls": "list",
    "s": "show",
    "rel": "distance",
    "e": "edit",
    "p": "parent",
    "ep": "edit-parent",
    "up": "unlink-parent",
    "pair": "partner",
    "unpair": "unlink-partner",
    "epair": "edit-partner",
    "t": "tree",
    "review": "review-parents",
    "dot": "export-dot",
    "cp": "clear-parents",
    "cc": "clear-children",
    "cpartners": "clear-partners",
}


def person_label(person):
    label = f"{person['name']} [#{person['id']}]"
    dates = []
    birth = person["birth_date"]
    if birth is not None:
        dates.append(f"b. {birth}")
    if person["death_year"] is not None:
        dates.append(f"d. {person['death_year']}")
    return label + (f" ({', '.join(dates)})" if dates else "")


def show_person(tree, person_id):
    person = tree.get_person(person_id)
    people = {person["id"]: person for person in tree.list_people()}
    parents = tree.list_parent_links()
    partners = tree.list_partner_links()

    def labels(ids):
        relatives = sorted((people[key] for key in ids), key=lambda item: (item["name"].casefold(), item["id"]))
        return "; ".join(person_label(relative) for relative in relatives) or "None recorded"

    def reference(person_key):
        relative = people[person_key]
        return f"{relative['name']} [#{relative['id']}]"

    parent_ids = [link["parent_id"] for link in parents if link["child_id"] == person_id]
    child_ids = [link["child_id"] for link in parents if link["parent_id"] == person_id]
    partner_ids = [
        link["partner_id"] if link["person_id"] == person_id else link["person_id"]
        for link in partners if person_id in (link["person_id"], link["partner_id"])
    ]
    lines = [
        person_label(person),
        f"Parents: {labels(parent_ids)}",
        f"Children: {labels(child_ids)}",
        f"Partners: {labels(partner_ids)}",
        f"Gender: {person['gender'] or 'Not recorded'}",
        f"Notes: {person['notes'] or 'None recorded'}",
    ]
    for label, source in (
        ("Name", person["name_source"]),
        ("Birth", person["birth_source"]),
        ("Death", person["death_source"]),
        ("Gender", person["gender_source"]),
    ):
        if source:
            lines.append(f"{label} source: {source}")

    for link in parents:
        if link["child_id"] == person_id:
            lines.append(
                f"Parent link: {reference(link['parent_id'])} "
                f"({link['relationship_type']})"
                + (f"; source: {link['source']}" if link["source"] else "")
            )
        if link["parent_id"] == person_id:
            lines.append(
                f"Child link: {reference(link['child_id'])} "
                f"({link['relationship_type']})"
                + (f"; source: {link['source']}" if link["source"] else "")
            )
    for link in partners:
        if person_id in (link["person_id"], link["partner_id"]) and link["source"]:
            relative_id = (
                link["partner_id"] if link["person_id"] == person_id else link["person_id"]
            )
            lines.append(
                f"Partner link source ({reference(relative_id)}): {link['source']}"
            )
    return "\n".join(lines)


def ancestor_paths(person_id, parents):
    paths = {person_id: [(person_id,)]}
    stack = [(person_id, (person_id,))]
    while stack:
        current, path = stack.pop()
        for parent_id in parents[current]:
            parent_path = path + (parent_id,)
            paths.setdefault(parent_id, []).append(parent_path)
            stack.append((parent_id, parent_path))
    return paths


def relatedness_contributions(start_paths, target_paths):
    contributions = {}
    shortest_path = None
    for ancestor_id in sorted(start_paths.keys() & target_paths.keys()):
        contribution = 0.0
        pair_count = 0
        for start_path in start_paths[ancestor_id]:
            for target_path in target_paths[ancestor_id]:
                if not set(start_path[:-1]).isdisjoint(target_path[:-1]):
                    continue
                pair_count += 1
                contribution += 0.5 ** (len(start_path) + len(target_path) - 2)
                path = start_path + tuple(reversed(target_path[:-1]))
                if shortest_path is None or (len(path), path) < (len(shortest_path), shortest_path):
                    shortest_path = path
        if pair_count:
            contributions[ancestor_id] = (contribution, pair_count)
    return contributions, shortest_path


def format_distance(tree, person_id, other_person_id):
    people = {person["id"]: person for person in tree.list_people()}
    start = tree.get_person(person_id)
    target = tree.get_person(other_person_id)
    if person_id == other_person_id:
        return (
            "Estimated coefficient of relatedness: 1.000000 (100%)\n"
            "Self-comparison."
        )

    parents = {key: set() for key in people}
    for link in tree.list_parent_links():
        if link["relationship_type"] == "biological":
            parents[link["child_id"]].add(link["parent_id"])

    start_paths = ancestor_paths(person_id, parents)
    target_paths = ancestor_paths(other_person_id, parents)
    contributions, shortest_path = relatedness_contributions(start_paths, target_paths)
    if not contributions:
        return (
            f"Estimated coefficient of relatedness: 0.000000 (0%)\n"
            f"No recorded shared biological ancestor connects {person_label(start)} "
            f"and {person_label(target)}.\n"
            "Adoptive and unknown links are excluded."
        )

    coefficient = sum(value for value, _ in contributions.values())
    lines = [
        f"Estimated coefficient of relatedness: {coefficient:.6f} "
        f"({coefficient:.2%})",
        "Shared-ancestor contributions:",
    ]
    for ancestor_id in sorted(
        contributions,
        key=lambda key: (people[key]["name"].casefold(), key),
    ):
        value, path_pairs = contributions[ancestor_id]
        lines.append(
            f"- {person_label(people[ancestor_id])}: {value:.6f} "
            f"({path_pairs} independent path pair(s))"
        )

    if shortest_path:
        distance = len(shortest_path) - 1
        noun = "link" if distance == 1 else "links"
        labels = " -> ".join(person_label(people[key]) for key in shortest_path)
        lines.extend((f"Shortest path: {distance} parent-child {noun}", f"Path: {labels}"))

    ancestors = start_paths.keys() | target_paths.keys()
    if any(len(parents[key]) > 2 for key in ancestors):
        lines.append(
            "Warning: at least one person has more than two recorded parents; "
            "the genetic estimate may not be biologically meaningful."
        )
    if any(
        link["relationship_type"] != "biological"
        and (link["parent_id"] in ancestors or link["child_id"] in ancestors)
        for link in tree.list_parent_links()
    ):
        lines.append(
            "Note: adoptive or unknown parent links are excluded from this estimate."
        )
    return "\n".join(lines)


def format_tree(tree, person_id, direction, depth):
    root = tree.get_person(person_id)
    people = {person["id"]: person for person in tree.list_people()}
    relatives = {key: [] for key in people}
    for link in tree.list_parent_links():
        parent_id, child_id = link["parent_id"], link["child_id"]
        if direction == "ancestors":
            relatives[child_id].append(parent_id)
        else:
            relatives[parent_id].append(child_id)

    lines = [person_label(root)]

    def visit(key, prefix, remaining):
        if remaining == 0:
            if relatives[key]:
                lines.append(prefix + "… more generations (increase --depth)")
            return
        ids = sorted(relatives[key], key=lambda key: (people[key]["name"].casefold(), key))
        for index, relative_id in enumerate(ids):
            last = index == len(ids) - 1
            lines.append(prefix + ("└── " if last else "├── ") + person_label(people[relative_id]))
            visit(relative_id, prefix + ("    " if last else "│   "), remaining - 1)

    visit(person_id, "", depth)
    return "\n".join(lines)


def format_entire_tree(tree):
    people = {person["id"]: person for person in tree.list_people()}
    if not people:
        return "No people yet. Use the add command to start."

    children = {key: [] for key in people}
    has_parent = set()
    for link in tree.list_parent_links():
        children[link["parent_id"]].append(link["child_id"])
        has_parent.add(link["child_id"])

    def sort_key(person_id):
        person = people[person_id]
        return person["name"].casefold(), person_id

    roots = sorted((key for key in people if key not in has_parent), key=sort_key)
    lines = []
    shown = set()

    for root_index, root_id in enumerate(roots):
        if root_index:
            lines.append("")
        lines.append(person_label(people[root_id]))
        shown.add(root_id)
        stack = [
            (child_id, "", index == len(children[root_id]) - 1)
            for index, child_id in reversed(list(enumerate(
                sorted(children[root_id], key=sort_key)
            )))
        ]

        while stack:
            person_id, prefix, last = stack.pop()
            lines.append(
                prefix + ("└── " if last else "├── ") + person_label(people[person_id])
                + (" (already shown above)" if person_id in shown else "")
            )
            if person_id in shown:
                continue
            shown.add(person_id)
            child_ids = sorted(children[person_id], key=sort_key)
            child_prefix = prefix + ("    " if last else "│   ")
            stack.extend(
                (child_id, child_prefix, index == len(child_ids) - 1)
                for index, child_id in reversed(list(enumerate(child_ids)))
            )

    return "\n".join(lines)


def format_graphviz(tree):
    def quote(value):
        return json.dumps(value, ensure_ascii=False)

    lines = [
        "digraph family_tree {",
        "  graph [rankdir=TB];",
        "  node [shape=box];",
    ]
    for person in tree.list_people():
        attributes = [f"label={quote(person_label(person))}"]
        if person["notes"]:
            attributes.append(f"tooltip={quote(person['notes'])}")
        lines.append(f"  person_{person['id']} [{', '.join(attributes)}];")

    for link in tree.list_parent_links():
        attributes = [f"label={quote(link['relationship_type'])}"]
        if link["source"]:
            attributes.append(f"tooltip={quote(link['source'])}")
        lines.append(
            f"  person_{link['parent_id']} -> person_{link['child_id']} "
            f"[{', '.join(attributes)}];"
        )

    for link in tree.list_partner_links():
        attributes = ['dir=none', 'style=dashed', 'label="partners"', 'constraint=false']
        if link["source"]:
            attributes.append(f"tooltip={quote(link['source'])}")
        lines.append(
            f"  person_{link['person_id']} -> person_{link['partner_id']} "
            f"[{', '.join(attributes)}];"
        )
    lines.append("}")
    return "\n".join(lines)


def person_completions(prefix, people):
    prefix = prefix.casefold()
    return [
        f"{person['name']} [#{person['id']}]"
        for person in sorted(people, key=lambda person: (person["name"].casefold(), person["id"]))
        if person["name"].casefold().startswith(prefix)
    ]


def resolve_person_reference(value, people):
    value = value.strip()
    if value.isdecimal():
        person_id = int(value)
        if any(person["id"] == person_id for person in people):
            return person_id
        return None
    if value.endswith("]") and " [#" in value:
        name, id_value = value.rsplit(" [#", 1)
        id_value = id_value[:-1]
        if id_value.isdecimal():
            person_id = int(id_value)
            if any(
                person["id"] == person_id and person["name"] == name
                for person in people
            ):
                return person_id
    matches = [
        person["id"] for person in people
        if person["name"].casefold() == value.casefold()
    ]
    return matches[0] if len(matches) == 1 else None


def require_person_reference(value, people):
    person_id = resolve_person_reference(value, people)
    if person_id is None:
        raise ValueError(
            f"Person reference {value!r} is unknown or ambiguous. "
            "Use a unique name, ID, or Name [#ID]."
        )
    return person_id


def add_person_interactively(tree, input_fn=input):
    print("Add a family member (press Ctrl+C to cancel).")
    name = input_fn("Name: ").strip()
    while not name:
        print("Name must not be blank.")
        name = input_fn("Name: ").strip()

    birth_date = input_fn("Birth year or date (optional): ").strip() or None
    death_year = None
    while True:
        value = input_fn("Death year (optional): ").strip()
        if not value:
            break
        try:
            death_year = int(value)
            break
        except ValueError:
            print("Enter a whole-number year, or leave it blank.")

    notes = input_fn("Notes (optional): ").strip()
    gender = input_fn("Gender or self-description (optional): ").strip() or None
    name_source = input_fn("Name source (optional): ").strip()
    birth_source = input_fn("Birth source (optional): ").strip() if birth_date else ""
    death_source = input_fn("Death source (optional): ").strip() if death_year else ""
    gender_source = input_fn("Gender source (optional): ").strip() if gender else ""

    people = tree.list_people()
    if people:
        print("Existing people:")
        for person in people:
            print(f"  {person['id']}: {person['name']}")
    parent_details = []
    if readline is not None and input_fn is input and sys.stdin.isatty():
        previous_completer = readline.get_completer()
        previous_delimiters = readline.get_completer_delims()
        suggestions = []

        def complete_person(text, state):
            nonlocal suggestions
            if state == 0:
                suggestions = person_completions(text, people)
            return suggestions[state] if state < len(suggestions) else None

        readline.set_completer(complete_person)
        readline.set_completer_delims("\t\n")
        readline.parse_and_bind("tab: menu-complete")
    else:
        previous_completer = None
        previous_delimiters = None
        complete_person = None

    try:
        while people:
            value = input_fn("Parent name or ID (Enter when done): ").strip()
            if not value:
                break
            parent_id = resolve_person_reference(value, people)
            if parent_id is None:
                print("Enter an exact name, an ID, or a unique name from the list.")
                continue
            parent = next(person for person in people if person["id"] == parent_id)
            if any(existing_id == parent_id for existing_id, _, _ in parent_details):
                print(f"{parent['name']} has already been selected.")
                continue
            relationship_type = "unknown"
            while True:
                value = input_fn(
                    f"Relationship with {parent['name']} [biological/adoptive/unknown] "
                    "(default unknown): "
                ).strip().lower()
                if not value:
                    break
                if value in ("biological", "adoptive", "unknown"):
                    relationship_type = value
                    break
                print("Choose biological, adoptive, or unknown.")
            source = input_fn(f"Source for {parent['name']} relationship (optional): ").strip()
            parent_details.append((parent_id, relationship_type, source))
    finally:
        if complete_person is not None:
            readline.set_completer(previous_completer)
            readline.set_completer_delims(previous_delimiters)

    key = tree.add_person(
        name, birth_date, death_year, notes,
        gender=gender,
        name_source=name_source, birth_source=birth_source, death_source=death_source,
        gender_source=gender_source,
    )
    for parent_id, relationship_type, source in parent_details:
        tree.add_parent(parent_id, key, relationship_type, source)
    result = f"Added {person_label(tree.get_person(key))}."
    if parent_details:
        result += f" Linked to {len(parent_details)} parent(s)."
    return result


def review_unknown_parents(tree, input_fn=input):
    people = {person["id"]: person for person in tree.list_people()}
    unknown_links = [
        link for link in tree.list_parent_links()
        if link["relationship_type"] == "unknown"
    ]
    unknown_links.sort(key=lambda link: (
        people[link["child_id"]]["name"].casefold(),
        people[link["parent_id"]]["name"].casefold(),
        link["parent_id"],
    ))
    if not unknown_links:
        return "No unknown parent relationships to review."

    counts = {"biological": 0, "adoptive": 0, "unknown": 0, "skipped": 0}
    print(f"Reviewing {len(unknown_links)} unknown parent relationship(s).")
    print("Enter b for biological, a for adoptive, u to keep unknown, or s to skip.")
    for index, link in enumerate(unknown_links, start=1):
        parent = people[link["parent_id"]]
        child = people[link["child_id"]]
        print(f"\n[{index}/{len(unknown_links)}] {person_label(parent)} -> {person_label(child)}")
        while True:
            answer = input_fn("[b]iological / [a]doptive / [u]nknown / [s]kip: ").strip().lower()
            choices = {
                "b": "biological", "biological": "biological",
                "a": "adoptive", "adoptive": "adoptive",
                "u": "unknown", "unknown": "unknown",
                "s": "skipped", "skip": "skipped",
            }
            if answer in choices:
                relationship_type = choices[answer]
                break
            print("Choose biological, adoptive, unknown, or skip.")

        if relationship_type == "skipped":
            counts["skipped"] += 1
            continue

        source = input_fn(
            f"Source (Enter to keep {link['source'] or 'none'}): "
        ).strip()
        tree.update_parent_link(
            link["parent_id"],
            link["child_id"],
            relationship_type,
            source if source else None,
        )
        counts[relationship_type] += 1

    return (
        "Review complete: "
        f"{counts['biological']} biological, {counts['adoptive']} adoptive, "
        f"{counts['unknown']} kept unknown, {counts['skipped']} skipped."
    )


def review_missing_gender(tree, input_fn=input):
    people = [
        person for person in tree.list_people()
        if person["gender"] is None
    ]
    if not people:
        return "No people with gender not recorded to review."

    print(f"Reviewing {len(people)} person(s) with no recorded gender.")
    print("Enter a gender or self-description, or leave it blank to skip.")
    updated = 0
    skipped = 0
    for index, person in enumerate(people, start=1):
        print(f"\n[{index}/{len(people)}] {person_label(person)}")
        gender = input_fn("Gender or self-description (blank to skip): ").strip()
        if not gender:
            skipped += 1
            continue

        source = input_fn("Source (optional): ").strip()
        tree.update_person(
            person["id"],
            person["name"],
            person["birth_date"],
            person["death_year"],
            person["notes"],
            gender=gender,
            gender_source=source if source else None,
        )
        updated += 1

    return f"Review complete: {updated} updated, {skipped} skipped."


def build_parser():
    parser = argparse.ArgumentParser(description="Build and explore a family tree in your terminal.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE,
                        help="SQLite file (default: data/family_tree.db beside main.py)")
    commands = parser.add_subparsers(dest="command", required=True)

    add = commands.add_parser("add", aliases=["a"], help="Add a person")
    add.add_argument("name")
    add.add_argument("--born", metavar="YEAR|YYYY-MM-DD", help="Birth year or full birth date, if known")
    add.add_argument("--died", type=int, help="Death year, if known")
    add.add_argument("--notes", default="")
    add.add_argument("--gender", help="Optional gender or self-description")
    add.add_argument("--name-source", default="", help="Source for the person's name")
    add.add_argument("--born-source", default="", help="Source for the birth detail")
    add.add_argument("--died-source", default="", help="Source for the death year")
    add.add_argument("--gender-source", default="", help="Source for the gender detail")
    commands.add_parser(
        "new", aliases=["n"], help="Interactively add a person and optional parent links"
    )
    commands.add_parser(
        "review-parents", aliases=["review"], help="Review unknown parent relationships one by one"
    )
    commands.add_parser(
        "review-gender", help="Review people without a recorded gender"
    )

    commands.add_parser("list", aliases=["ls"], help="List all people and their IDs")
    export_dot = commands.add_parser(
        "export-dot", aliases=["dot"], help="Export the family tree as a Graphviz DOT file"
    )
    export_dot.add_argument("output", type=Path, help="Path for the generated .dot file")
    completions = commands.add_parser("complete-people", help=argparse.SUPPRESS)
    completions.add_argument("prefix", nargs="?", default="")
    show = commands.add_parser(
        "show", aliases=["s"], help="Show a person and their immediate relatives"
    )
    show.add_argument("person_id", metavar="PERSON")

    distance = commands.add_parser(
        "distance", aliases=["rel"],
        help="Estimate relatedness between two people from their ancestry"
    )
    distance.add_argument("person_id", metavar="PERSON")
    distance.add_argument("other_person_id", metavar="PERSON")

    edit = commands.add_parser("edit", aliases=["e"], help="Update a person's details")
    edit.add_argument("person_id", metavar="PERSON")
    edit.add_argument("--name")
    birth = edit.add_mutually_exclusive_group()
    birth.add_argument("--born", metavar="YEAR|YYYY-MM-DD", help="Replace the birth year or full birth date")
    birth.add_argument("--clear-born", action="store_true", help="Remove both the birth year and date")
    death = edit.add_mutually_exclusive_group()
    death.add_argument("--died", type=int)
    death.add_argument("--clear-died", action="store_true")
    edit.add_argument("--notes", help='Use --notes "" to clear notes')
    gender = edit.add_mutually_exclusive_group()
    gender.add_argument("--gender", help="Set gender or self-description")
    gender.add_argument("--clear-gender", action="store_true", help="Remove the gender detail")
    edit.add_argument("--name-source", help="Set or clear the name source")
    edit.add_argument("--born-source", help="Set or clear the birth source")
    edit.add_argument("--died-source", help="Set or clear the death source")
    edit.add_argument("--gender-source", help="Set or clear the gender source")

    parent = commands.add_parser(
        "parent", aliases=["p"], help="Link one or more parents to a child (child ID last)"
    )
    parent.add_argument("parent_ids", nargs="+", metavar="PARENT",
                        help="IDs of the parents to link")
    parent.add_argument("child_id", metavar="CHILD", help="Child's name or ID, always last")
    parent.add_argument(
        "--type", choices=("biological", "adoptive", "unknown"), default="unknown",
        help="Type of parent relationship (default: unknown)",
    )
    parent.add_argument("--source", default="", help="Source for the parent relationship")

    edit_parent = commands.add_parser(
        "edit-parent", aliases=["ep"], help="Edit a parent link's type or source"
    )
    edit_parent.add_argument("parent_id", metavar="PARENT")
    edit_parent.add_argument("child_id", metavar="CHILD")
    edit_parent.add_argument("--type", choices=("biological", "adoptive", "unknown"))
    edit_parent.add_argument("--source", help="Set or clear the source")

    unlink_parent = commands.add_parser(
        "unlink-parent", aliases=["up"], help="Remove a parent-to-child link"
    )
    unlink_parent.add_argument("parent_id", metavar="PARENT")
    unlink_parent.add_argument("child_id", metavar="CHILD")
    for name, help_text in (
        ("partner", "Link two partners"),
        ("unlink-partner", "Remove a partner link"),
    ):
        alias = {"partner": "pair", "unlink-partner": "unpair"}[name]
        command = commands.add_parser(name, aliases=[alias], help=help_text)
        command.add_argument("person_id", metavar="PERSON")
        command.add_argument("partner_id", metavar="PARTNER")
        if name == "partner":
            command.add_argument("--source", default="", help="Source for the partner relationship")

    edit_partner = commands.add_parser(
        "edit-partner", aliases=["epair"], help="Edit a partner link's source"
    )
    edit_partner.add_argument("person_id", metavar="PERSON")
    edit_partner.add_argument("partner_id", metavar="PARTNER")
    edit_partner.add_argument("--source", required=True, help="Set or clear the source")

    for relation in ("parents", "children", "partners"):
        command = commands.add_parser(
            f"clear-{relation}",
            aliases=[{"parents": "cp", "children": "cc", "partners": "cpartners"}[relation]],
            help=f"Remove all links to a person's {relation}",
            description=f"Remove all links to a person's {relation}. Everyone stays in the database.",
        )
        command.add_argument("person_id", metavar="PERSON", help="Person whose links to clear")

    view = commands.add_parser(
        "tree", aliases=["t"], help="Print ancestors, descendants, or the entire tree"
    )
    view.add_argument("person_id", metavar="PERSON", nargs="?")
    view.add_argument("--all", action="store_true", help="Print the entire family tree")
    view.add_argument("--direction", choices=("ancestors", "descendants"), default="ancestors")
    view.add_argument("--depth", type=int, default=4,
                      help="Generations to display (0–20; default: 4)")
    return parser


def run(args, tree):
    args.command = COMMAND_ALIASES.get(args.command, args.command)
    if args.command == "complete-people":
        return "\n".join(person_completions(args.prefix, tree.list_people()))

    people = tree.list_people()
    single_reference_commands = {"show", "edit", "clear-parents", "clear-children",
                                 "clear-partners"}
    if args.command in single_reference_commands:
        args.person_id = require_person_reference(args.person_id, people)
    elif args.command == "distance":
        args.person_id = require_person_reference(args.person_id, people)
        args.other_person_id = require_person_reference(args.other_person_id, people)
    elif args.command in {"parent"}:
        args.parent_ids = [require_person_reference(value, people) for value in args.parent_ids]
        args.child_id = require_person_reference(args.child_id, people)
    elif args.command in {"edit-parent", "unlink-parent"}:
        args.parent_id = require_person_reference(args.parent_id, people)
        args.child_id = require_person_reference(args.child_id, people)
    elif args.command in {"partner", "unlink-partner", "edit-partner"}:
        args.person_id = require_person_reference(args.person_id, people)
        args.partner_id = require_person_reference(args.partner_id, people)
    elif args.command == "tree" and args.person_id is not None:
        args.person_id = require_person_reference(args.person_id, people)

    if args.command == "add":
        key = tree.add_person(
            args.name, args.born, args.died, args.notes,
            gender=args.gender,
            name_source=args.name_source,
            birth_source=args.born_source,
            death_source=args.died_source,
            gender_source=args.gender_source,
        )
        return f"Added {person_label(tree.get_person(key))}."
    if args.command == "new":
        return add_person_interactively(tree)
    if args.command == "review-parents":
        return review_unknown_parents(tree)
    if args.command == "review-gender":
        return review_missing_gender(tree)
    if args.command == "list":
        return "\n".join(person_label(person) for person in tree.list_people()) or "No people yet. Use the add command to start."
    if args.command == "export-dot":
        args.output.write_text(format_graphviz(tree) + "\n", encoding="utf-8")
        return f"Graphviz DOT exported to {args.output}."
    if args.command == "show":
        return show_person(tree, args.person_id)
    if args.command == "distance":
        return format_distance(tree, args.person_id, args.other_person_id)
    if args.command == "edit":
        person = tree.get_person(args.person_id)
        for argument, field in (("name", "name"), ("died", "death_year"), ("notes", "notes")):
            if getattr(args, argument) is not None:
                person[field] = getattr(args, argument)
        if args.name is not None and args.name_source is None:
            person["name_source"] = ""
        if args.gender is not None:
            person["gender"] = args.gender.strip() or None
            if args.gender_source is None:
                person["gender_source"] = ""
        if args.clear_gender:
            person["gender"] = None
            person["gender_source"] = ""
        elif args.gender_source is not None:
            person["gender_source"] = args.gender_source
        if args.born is not None:
            person["birth_date"] = args.born
            person["birth_source"] = args.born_source or ""
        if args.clear_born:
            person["birth_date"] = None
            person["birth_source"] = ""
        elif args.born_source is not None:
            person["birth_source"] = args.born_source
        if args.died is not None:
            person["death_source"] = args.died_source or ""
        if args.clear_died:
            person["death_year"] = None
            person["death_source"] = ""
        for argument, field in (
            ("name_source", "name_source"),
            ("died_source", "death_source"),
        ):
            if getattr(args, argument) is not None and not (
                argument == "died_source" and args.clear_died
            ):
                person[field] = getattr(args, argument)
        tree.update_person(person["id"], person["name"], person["birth_date"],
                           person["death_year"], person["notes"],
                           gender=person["gender"],
                           name_source=person["name_source"],
                           birth_source=person["birth_source"],
                           death_source=person["death_source"],
                           gender_source=person["gender_source"])
        return f"Updated {person_label(tree.get_person(person['id']))}."
    if args.command == "parent":
        added = tree.add_parents(args.parent_ids, args.child_id, args.type, args.source)
        if len(args.parent_ids) == 1:
            return "Parent relationship added." if added else "Parent relationship already exists."
        if not added:
            return "All requested parent relationships already exist."
        noun = "relationship" if added == 1 else "relationships"
        return f"Added {added} parent {noun}."
    if args.command == "edit-parent":
        if args.type is None and args.source is None:
            raise ValueError("Specify --type or --source.")
        tree.update_parent_link(args.parent_id, args.child_id, args.type, args.source)
        return "Parent relationship updated."
    if args.command == "partner":
        added = tree.add_partner(args.person_id, args.partner_id, args.source)
        return "Partner relationship added." if added else "Partner relationship already exists."
    if args.command == "edit-partner":
        tree.update_partner_link(args.person_id, args.partner_id, args.source)
        return "Partner relationship updated."
    if args.command == "unlink-parent":
        tree.remove_parent(args.parent_id, args.child_id)
        return "Parent relationship removed."
    if args.command == "unlink-partner":
        tree.remove_partner(args.person_id, args.partner_id)
        return "Partner relationship removed."
    clear_actions = {
        "clear-parents": (tree.clear_parents, "parent"),
        "clear-children": (tree.clear_children, "child"),
        "clear-partners": (tree.clear_partners, "partner"),
    }
    if args.command in clear_actions:
        clear_links, relation = clear_actions[args.command]
        removed = clear_links(args.person_id)
        noun = "link" if removed == 1 else "links"
        return f"Removed {removed} {relation} {noun} for person #{args.person_id}."
    if args.command == "tree":
        if args.all:
            if args.person_id is not None:
                raise ValueError("Do not specify a person ID with --all.")
            return format_entire_tree(tree)
        if args.person_id is None:
            raise ValueError("Specify a person ID or use --all.")
        if not 0 <= args.depth <= 20:
            raise ValueError("Depth must be between 0 and 20.")
        return format_tree(tree, args.person_id, args.direction, args.depth)
    raise ValueError("Unknown command.")


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.command = COMMAND_ALIASES.get(args.command, args.command)
    if args.command == "tree" and (args.all == (args.person_id is not None)):
        parser.error("specify either a person ID or --all")
    try:
        result = run(args, FamilyTree(args.database))
    except KeyboardInterrupt:
        if args.command in {"review-parents", "review-gender"}:
            print("Review interrupted; decisions made so far were saved.", file=sys.stderr)
        else:
            print("Cancelled; no person was added.", file=sys.stderr)
        return 1
    except EOFError:
        if args.command in {"review-parents", "review-gender"}:
            print("Review interrupted; decisions made so far were saved.", file=sys.stderr)
        else:
            print("Input ended before the person could be added.", file=sys.stderr)
        return 1
    except (ValueError, sqlite3.Error, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
