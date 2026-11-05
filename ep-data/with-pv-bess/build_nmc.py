"""Reproducible KiBaM -> NMC substitution; legacy input/results stay intact."""
from pathlib import Path
import argparse, hashlib, json, re, shutil, subprocess

ROOT = Path(__file__).resolve().parent
DEFAULT = Path('C:/Users/Franc/OneDrive/Desktop/Uni Documents/2026/Thesis/building_semantic/ornl_frp/implementation/ep-data/with-pv-bess')
EP = Path('C:/EnergyPlusV25-2-0')
BATTERY = 'Thesis NMC Battery'
SERIES, PARALLEL = 139, 139
CAPACITY = SERIES * PARALLEL * 3.342 * 3.2 / 1000

def objects(text):
    return [[v.strip() for v in obj.split(',')] for obj in re.sub(r'!.*', '', text).split(';') if obj.strip()]

def edit_objects(text, fn):
    """Preserve all unchanged objects/comments; edit only named electrical objects."""
    clean = re.sub(r'!.*', lambda m: ' ' * len(m.group()), text)
    edits = []
    for match in re.finditer(r'[^;]+;', clean):
        fields = [x.strip() for x in match.group().strip()[:-1].split(',')]
        new = fn(fields)
        if new != fields:
            start = match.start() + len(match.group()) - len(match.group().lstrip())
            edits.append((start, match.end(), '' if new is None else ',\n    '.join(map(str, new)) + ';'))
    for start, end, replacement in reversed(edits):
        text = text[:start] + replacement + text[end:]
    return text

def build(source):
    example = EP / 'ExampleFiles/ShopWithPVandLiIonBattery.idf'
    manifest = dict(energyplus_version='25.2.0', battery_object='ElectricLoadCenter:Storage:LiIonNMCBattery',
        battery_name=BATTERY, nominal_capacity_kWh=CAPACITY, series_cells=SERIES, parallel_strings=PARALLEL,
        cell_nominal_voltage_V=3.342, cell_capacity_Ah=3.2, design_power_kW=50,
        battery_mass_kg=342 * PARALLEL / 25, battery_surface_area_m2=4.26 * PARALLEL / 25,
        parameter_source=str(example), example_sha256=hashlib.sha256(example.read_bytes()).hexdigest(),
        idd_sha256=hashlib.sha256((EP/'Energy+.idd').read_bytes()).hexdigest(), models={})
    for coverage in (60, 80):
        src = source / f'RefBldgMediumOfficeNew2004_Chicago_PV{coverage}_KiBaM.idf'
        text = src.read_text()
        original = objects(text)
        assert sum(o[0].lower() == 'electricloadcenter:storage:battery' for o in original) == 1
        def change(o):
            kind = o[0].lower()
            if kind == 'electricloadcenter:storage:battery':
                # Cell defaults are made explicit, in installed 25.2 IDD field order.
                return ['ElectricLoadCenter:Storage:LiIonNMCBattery', BATTERY, '', '', 0,
                    'KandlerSmith', SERIES, PARALLEL, .20, .95, 342*PARALLEL/25, 4.26*PARALLEL/25,
                    1500, 7.5, 4.2, 3.53, 3.342, 3.342, 3.2, .8075, .976875, 1, .09]
            if kind.startswith('curve:') and o[1].startswith('Thesis KiBaM'):
                return None
            if kind == 'electricloadcenter:distribution':
                o = o.copy(); assert o[9] == 'Thesis KiBaM Battery'; o[9] = BATTERY
                return o
            if kind == 'output:variable' and o[1] == 'Thesis KiBaM Battery':
                if o[2] == 'Electric Storage Battery Charge State':
                    return None  # SOC fraction is used instead of the optional Ah diagnostic
                o = o.copy(); o[1] = BATTERY; return o
            return o
        result = edit_objects(text, change)
        result = result.replace('see manifest.json', 'see manifest_nmc.json')
        result = result.replace('! Example-derived KiBaM module parameters, 20 series x 10 parallel.',
            '! Generic NMC: 139 cells in series x 139 strings; see README_NMC.md for assumptions.')
        result += f'\n! NMC thermal diagnostic; no building zone receives battery losses.\nOutput:Variable,{BATTERY},Electric Storage Battery Temperature,Timestep;\n'
        # Verify complete preservation of thermal/HVAC/PV input objects.
        def protected(o):
            return not (o[0].lower().startswith('electricloadcenter:storage:') or
                o[0].lower() in ('electricloadcenter:distribution', 'output:variable') or
                (o[0].lower().startswith('curve:') and o[1].startswith('Thesis KiBaM')))
        assert [o for o in original if protected(o)] == [o for o in objects(result) if protected(o)]
        name = f'PV{coverage}_NMC'
        filename = f'RefBldgMediumOfficeNew2004_Chicago_{name}.idf'
        (ROOT/filename).write_text(result)
        manifest['models'][name] = dict(filename=filename, coverage=coverage/100,
            source_sha256=hashlib.sha256(src.read_bytes()).hexdigest(),
            generated_sha256=hashlib.sha256((ROOT/filename).read_bytes()).hexdigest(),
            thermal_HVAC_PV_objects_unchanged=True)
        # PV-only reference also supplies the existing MPC's PV forecast.
        for filename in [f'PV{coverage}_Only_timeseries.csv']:
            if (source/filename).resolve() != (ROOT/filename).resolve():
                shutil.copy2(source/filename, ROOT/filename)
    weather = next(source.glob('*.epw'))
    if weather.resolve() != (ROOT/weather.name).resolve(): shutil.copy2(weather, ROOT/weather.name)
    (ROOT/'manifest_nmc.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))

def run():
    manifest = json.loads((ROOT/'manifest_nmc.json').read_text())
    for name, info in manifest['models'].items():
        out = ROOT/'runs'/name
        if (out/'eplusout.sql').exists(): raise FileExistsError(f'Preserve existing results: {out}')
        out.mkdir(parents=True, exist_ok=True)
        with (out/'console.log').open('w') as log:
            subprocess.run([str(EP/'energyplus.exe'), '-w', str(next(ROOT.glob('*.epw'))), '-d', str(out), str(ROOT/info['filename'])],
                cwd=out, stdout=log, stderr=subprocess.STDOUT, check=True)
        err = (out/'eplusout.err').read_text()
        if '** Severe **' in err or '** Fatal **' in err: raise RuntimeError(err)
        print(name, err[err.rfind('EnergyPlus Completed Successfully'):].strip(), flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['build', 'run'])
    parser.add_argument('--source', type=Path, default=DEFAULT)
    args = parser.parse_args()
    build(args.source) if args.action == 'build' else run()
