"""Inspect/index resources or execute explicit typed operations."""
import argparse
import json
import sqlite3
from dataclasses import asdict
from ultron_resources.catalog import ResourceError, AmbiguousResource
from ultron_resources.config import create_service


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['index', 'search', 'open', 'launch', 'read', 'run'])
    parser.add_argument('target', nargs='?')
    parser.add_argument('--root')
    parser.add_argument('--editor')
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--argument', action='append', default=[])
    parser.add_argument('--scan-seconds', type=float, default=30)
    parser.add_argument('--max-entries', type=int, default=100_000)
    args = parser.parse_args()
    try:
        service = create_service()
        if args.operation == 'index':
            roots = [args.root] if args.root else service.catalog.policy.roots
            complete = True
            for root in roots:
                report = service.catalog.index(root, max_seconds=args.scan_seconds, max_entries=args.max_entries)
                print(json.dumps(report, ensure_ascii=False), flush=True)
                complete = complete and report['complete']
            return 0 if complete else 2
        if not args.target:
            parser.error('This operation requires a target.')
        if args.operation == 'search':
            result = [item.to_dict() for item in service.catalog.search(args.target, root=args.root)]
        elif args.operation == 'read':
            result = {'text': service.read_text(args.target, root=args.root)}
        elif args.operation == 'open':
            result = asdict(service.open(args.target, root=args.root, editor=args.editor))
        elif args.operation == 'launch':
            result = asdict(service.launch(args.target, root=args.root, arguments=args.argument))
        else:
            result = asdict(service.run_script(args.target, root=args.root, arguments=args.argument, timeout=args.timeout))
        print(json.dumps(result, ensure_ascii=False))
        return 0 if not isinstance(result, dict) or result.get('success', True) else 1
    except AmbiguousResource as exc:
        print(json.dumps({'success': False, 'error': str(exc), 'candidates': exc.candidates}))
        return 1
    except (ResourceError, OSError, ValueError, sqlite3.Error) as exc:
        print(json.dumps({'success': False, 'error': str(exc)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
