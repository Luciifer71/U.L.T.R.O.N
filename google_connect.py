"""One-time local Google consent and private cached review. Never logs tokens."""
import argparse
import json
import sqlite3
from ultron_control.google_updates import connect, disconnect, private_dir, connection_diagnostics, failure_details


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['connect', 'disconnect', 'review', 'doctor'])
    parser.add_argument('--client', help='Google Desktop OAuth client JSON, outside the repository')
    args = parser.parse_args()
    try:
        if args.command == 'doctor':
            report = connection_diagnostics()
            print(json.dumps(report, indent=2))
            return int(any(isinstance(value, dict) and value.get('status') == 'failed' for value in report.values()))
        if args.command == 'connect':
            if not args.client:
                parser.error('--client is required for connect')
            connect(args.client)
            print('Google read-only access saved in Windows Credential Manager. Restart Ultron to begin syncing.')
        elif args.command == 'disconnect':
            disconnect()
            print('Local credentials and cache removed. Also revoke Ultron in your Google account connections.')
        else:
            path = private_dir() / 'updates.sqlite3'
            if not path.exists():
                print('No cached Google updates. Connect and start Ultron first.')
                return 1
            with sqlite3.connect(path) as db:
                checked = db.execute("SELECT value FROM state WHERE key='checked'").fetchone()
                print('Cached snapshot timestamp (Unix seconds):', checked[0] if checked else 'unavailable')
                print('Potentially important mail (up to 50; heuristic, may be stale):')
                for subject, reason in db.execute("SELECT subject, reason FROM messages WHERE reason != '' LIMIT 50"):
                    print(f'- {subject}: {reason}')
                row = db.execute("SELECT value FROM state WHERE key='calendar'").fetchone()
                for event in json.loads(row[0]) if row else []:
                    print(f"- Calendar: {event['start']} {event['title']}")
        return 0
    except Exception as error:
        print(json.dumps(failure_details(error), indent=2))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
