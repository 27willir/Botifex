import argparse
import json
import sys

from db import export_user_data, purge_user_data, close_database


def main():
    parser = argparse.ArgumentParser(description="Export or purge user data (GDPR tooling).")
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export", help="Export all data associated with a username.")
    export_parser.add_argument("username", help="Username to export.")
    export_parser.add_argument("--outfile", "-o", help="Path to write JSON export. Defaults to stdout.")

    purge_parser = subparsers.add_parser("purge", help="Purge all data associated with a username.")
    purge_parser.add_argument("username", help="Username to purge.")
    purge_parser.add_argument("--confirm", action="store_true", help="Required flag to confirm purging.")

    args = parser.parse_args()

    try:
        if args.command == "export":
            payload = export_user_data(args.username)
            if args.outfile:
                with open(args.outfile, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, indent=2, default=str)
                print(f"Exported data for {args.username} to {args.outfile}")
            else:
                json.dump(payload, sys.stdout, indent=2, default=str)
                print()
        elif args.command == "purge":
            if not args.confirm:
                parser.error("Purge requires --confirm flag.")
            purge_user_data(args.username)
            print(f"Purged data for {args.username}")
    finally:
        close_database()


if __name__ == "__main__":
    main()

