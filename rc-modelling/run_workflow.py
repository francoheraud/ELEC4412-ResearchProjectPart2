"""CLI entry point. Run from any directory; default inputs are ../ep-data."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
from pathlib import Path
import argparse
from rc_workflow import Config,run

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--implementation',type=Path,default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parent/'results')
    parser.add_argument('--force-energyplus',action='store_true')
    args=parser.parse_args();run(Config(implementation=args.implementation,output=args.output),args.force_energyplus)
