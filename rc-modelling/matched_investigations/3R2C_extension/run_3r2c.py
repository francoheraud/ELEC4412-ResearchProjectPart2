"""Isolated 3R2C extension; historical 1R/2R1C outputs are frozen comparators."""
import argparse
from rc_engine import *
from run_investigations import run_case, save_json

HERE=Path(__file__).resolve().parent
NAMES=['local_1R_wall','local_2R1C_wall','local_3R2C_wall']

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--implementation',type=Path,default=DEFAULT_IMPLEMENTATION)
    parser.add_argument('--report-only',action='store_true')
    args=parser.parse_args()
    data=load_inputs(args.implementation,HERE); splits=split_blocks(data)
    cases={n:case_definitions(data)[n] for n in NAMES}
    for name in NAMES[:2]:
        assert (HERE/'cases'/name/'complete.json').exists()
        contract=json.loads((HERE/'cases'/name/'contract.json').read_text())
        assert contract['data_sha256']==data['source_sha256']
        assert contract['config']==cases[name]
        assert contract['lambdas']==LAMBDAS.tolist() and contract['methods']==METHODS
    if not args.report_only:
        save_json(HERE/'extension_protocol.json',dict(
            cases=cases,data_sha256=data['source_sha256'],lambdas=LAMBDAS.tolist(),methods=METHODS,
            comparison='Same local candidate mask, fixed zone-air C, wall bounds, inputs, seasonal splits and 72 h conditioning as the frozen 1R/2R1C comparators.',
            formulation='3R2C: endpoint--Rtotal/3--Ctotal/2--Rtotal/3--Ctotal/2--Rtotal/3--endpoint. Rtotal=1/G; Ctotal=4G*tau_reference.',
            interpretation='Preserves total resistance and capacitance, not modal timescales. Both additional storage masses are tied; no independent capacity or resistance split is fitted.',
            modes='For fixed endpoint temperatures: slow tau=2*tau_reference/3, fast tau=2*tau_reference/9. These are not the eigenmode timescales of the complete network.',
            storage_categories=['interzone','outdoor_storage','plenum_lower'],
            other_paths='Outdoor direct, upper-plenum and ground stay 1R.',
            conditioning='Exact first-order-hold reconstruction from past measured endpoints; initialise at linear steady-state temperature profile. No future measurements in initial state.',
            selection='Minimum 24 h validation RMSE; separate fewest-state choice within 0.02 C, then active conductances and RMSE.',
            parameter_count='Active branch conductances plus two heat-input gains. Each retained 3R2C branch adds two states but no extra independent parameters relative to a matched 2R1C branch.',
            limitations=['Exploratory reused test periods.','Known future heat inputs and boundary temperatures.','Topology is rediscovered for each family; not a fixed-topology order test.','Transferred wall area bound mismatch is retained to keep the comparison matched.','Equal R and C allocation is one particular 3R2C assumption, not an optimisation over every 3R2C realisation.','3R2C internal fast mode may be shorter than sampling interval.','No MPC changes.'],
            source_hashes={p.name:sha(p) for p in HERE.glob('*.py')}))
        run_case(data,splits,'local_3R2C_wall',cases['local_3R2C_wall'])
    import make_reports
    make_reports.GROUPS={'02_branch_complexity':NAMES}
    make_reports.make_reports(data,cases)
    interpretation=HERE/'02_branch_complexity/INTERPRETATION.md'
    text=interpretation.read_text(encoding='utf-8')
    text=text.replace('between 1R and 2R1C','between 1R, 2R1C and 3R2C')
    text+='\n## 3R2C definition\n\nThree equal resistances and two equal capacitances preserve the 2R1C total resistance and total storage capacitance for a given G. The saved tau is a reference scale Ctotal/(4G), not the 3R2C modal time constant. With fixed endpoints the two mode time constants are 2*tau/3 and 2*tau/9. Every designated storage category changes together. The wall bounds and their known area-transfer limitation remain unchanged. See extension_protocol.json.\n'
    interpretation.write_text(text,encoding='utf-8')
    # Generic report helper was originally written for three investigation groups.
    verification=json.loads((HERE/'verification.json').read_text())
    verification['shared_reference']='Frozen local 1R and 2R1C comparators; only the 3R2C case was newly fitted.'
    save_json(HERE/'verification.json',verification)
    (HERE/'RESULTS.md').write_text(text,encoding='utf-8')
    from finalise import main as finalise
    finalise()

if __name__=='__main__': main()
