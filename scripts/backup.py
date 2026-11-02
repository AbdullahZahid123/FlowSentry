"""Binary-safe Compose PostgreSQL backup and empty-database restore."""
import argparse
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["backup", "restore"])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--project")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    compose = ["docker", "compose"] + (["-p", args.project] if args.project else [])
    base = compose + ["exec", "-T", "postgres"]
    if args.action == "backup":
        if not args.output:
            parser.error("backup requires --output")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation prevents accidental replacement of a good backup.
        with args.output.open("xb") as stream:
            result = subprocess.run(base + ["pg_dump", "-U", "flowsentry", "-d", "flowsentry", "-Fc"], cwd=root, stdout=stream)
        if result.returncode:
            raise SystemExit("Backup failed; the newly-created output is incomplete. Keep an earlier good backup.")
        print("Backup written to " + str(args.output))
    else:
        if not args.input or not args.input.is_file():
            parser.error("restore requires an existing --input file")
        if not args.project or args.project == "flowsentry":
            parser.error("restore requires a distinct --project for a new empty deployment")
        probe = subprocess.run(base + ["psql", "-U", "flowsentry", "-d", "flowsentry", "-Atc",
            "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"],
            cwd=root, check=True, capture_output=True, text=True)
        if probe.stdout.strip() != "0":
            raise SystemExit("Restore refused: target database is not empty.")
        with args.input.open("rb") as stream:
            subprocess.run(base + ["pg_restore", "-U", "flowsentry", "-d", "flowsentry", "--no-owner", "--exit-on-error", "--single-transaction"],
                           cwd=root, stdin=stream, check=True)
        print("Backup restored into empty project " + args.project)


if __name__ == "__main__":
    main()
