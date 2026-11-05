"""Run the unchanged scientific engines in a fresh, isolated output directory."""
import argparse
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--label', required=True)
    p.add_argument('--extension', action='store_true', help='Fit 3R2C with frozen 1R/2R1C comparators.')
    args = p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', args.label):
        p.error('Use a label containing letters, digits, underscores or hyphens.')
    source = ROOT/'rc-modelling/matched_investigations'
    if args.extension: source /= '3R2C_extension'
    output = ROOT/'reruns'/args.label
    if output.exists(): p.error('Output exists; choose a fresh label.')
    output.mkdir(parents=True)
    for f in source.glob('*.py'): shutil.copy2(f, output/f.name)
    shutil.copytree(source/'inputs', output/'inputs')
    if args.extension:
        for name in ['local_1R_wall','local_2R1C_wall']:
            shutil.copytree(source/'cases'/name, output/'cases'/name)
    sys.path.insert(0, str(output))
    import rc_engine
    rc_engine.DEFAULT_IMPLEMENTATION = ROOT
    sys.argv = ['run_3r2c.py' if args.extension else 'run_investigations.py',
                '--implementation', str(ROOT)]
    if args.extension:
        import run_3r2c as runner
    else:
        import run_investigations as runner
    runner.main()

if __name__ == '__main__': main()
