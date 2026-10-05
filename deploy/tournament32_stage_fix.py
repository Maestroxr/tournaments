"""Prepare an isolated candidate; never edit production or start services.

Run beside stage-query-payload.json and test_stage_query_budget.py.
The resulting candidate uses the server's source, preserving its existing fixes.
"""
import argparse
import ast
import json
from pathlib import Path
import shutil
import tempfile


def replace_properties(source, replacements):
    tree = ast.parse(source)
    mode = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Mode')
    lines = source.splitlines(keepends=True)
    changes = []
    for name, content in replacements.items():
        node = next(n for n in mode.body if isinstance(n, ast.FunctionDef) and n.name == name)
        actual = ast.dump(ast.Module(body=node.body, type_ignores=[]), include_attributes=False)
        expected_node = ast.parse(content['old']).body[0]
        expected = ast.dump(ast.Module(body=expected_node.body, type_ignores=[]), include_attributes=False)
        if actual != expected:
            raise RuntimeError(f'{name} differs from reviewed source; refusing to patch')
        start = min([node.lineno] + [d.lineno for d in node.decorator_list]) - 1
        changes.append((start, node.end_lineno, content['new']))
    for start, end, new in sorted(changes, reverse=True):
        lines[start:end] = [new + '\n']
    updated = ''.join(lines)
    updated = 'from django.db.models import Count as _StageConfirmationCount\n' + updated
    updated = updated.replace("confirmation_count=Count('confirmations')", "confirmation_count=_StageConfirmationCount('confirmations')")
    ast.parse(updated)
    return updated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('/home/dev/backgammon-tournaments-backend/tournaments'))
    args = parser.parse_args()
    bundle = Path(__file__).resolve().parent
    payload = json.loads((bundle / 'stage-query-payload.json').read_text(encoding='utf-8'))
    source_file = args.source / 'tournaments/models.py'
    updated = replace_properties(source_file.read_text(encoding='utf-8'), payload)
    root = Path(tempfile.mkdtemp(prefix='tournament32-candidate-'))
    candidate = root / 'app'
    shutil.copytree(args.source, candidate, ignore=shutil.ignore_patterns(
        '*.sqlite3*', '*.db', '__pycache__', '.env', '.git', 'media', 'staticfiles', '*.log',
    ))
    (candidate / 'tournaments/models.py').write_text(updated, encoding='utf-8')
    shutil.copy2(bundle / 'test_stage_query_budget.py', candidate / 'tournaments/test_stage_query_budget.py')
    shutil.copy2(bundle / 'run_stage_checks.py', candidate / 'run_stage_checks.py')
    print(f'CANDIDATE={candidate}')
    print('Production source and database were not modified.')
    print('Run explicitly to test the candidate:')
    print(f'cd {candidate} && /home/dev/backgammon-tournaments-backend/venv/bin/python run_stage_checks.py')


if __name__ == '__main__':
    main()
