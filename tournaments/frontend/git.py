import pathlib
import subprocess


def get_head_info():
    """Build metadata must never stop the application from booting without a Git checkout."""
    try:
        result = subprocess.run(
            ['git', 'show', '--no-patch', '--format=%H%n%cs', 'HEAD'],
            cwd=pathlib.Path(__file__).parents[1], capture_output=True, text=True, timeout=3,
        )
        lines = result.stdout.strip().splitlines()
        if result.returncode == 0 and len(lines) == 2:
            return {'sha': lines[0], 'date': lines[1]}
    except (OSError, subprocess.TimeoutExpired):
        pass
    return {'sha': 'unknown', 'date': 'unknown'}
