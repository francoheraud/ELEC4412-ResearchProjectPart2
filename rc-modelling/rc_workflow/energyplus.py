"""Add reporting only, then obtain the missing thermal inputs in an isolated run."""
from pathlib import Path
import re, hashlib, json, subprocess
import numpy as np

VARIABLES = [
    'Zone Mean Air Temperature', 'Site Outdoor Air Drybulb Temperature',
    'Zone Air System Sensible Heating Rate', 'Zone Air System Sensible Cooling Rate',
    'Zone Total Internal Convective Heating Rate', 'Zone Total Internal Radiant Heating Rate',
    'Zone Total Internal Visible Radiation Heating Rate',
    'Zone Infiltration Sensible Heat Gain Energy', 'Zone Infiltration Sensible Heat Loss Energy',
    'Surface Window Transmitted Solar Radiation Rate',
    'Zone Thermostat Heating Setpoint Temperature', 'Zone Thermostat Cooling Setpoint Temperature',
    'Zone People Occupant Count',
    'Zone Air Heat Balance Outdoor Air Transfer Rate',
]

def objects(text):
    return [[f.strip() for f in s.split(',')] for s in re.sub(r'!.*','',text).split(';') if s.strip()]

def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def metadata(path):
    obs=objects(Path(path).read_text(encoding='utf-8-sig'))
    zones=[o[1].upper() for o in obs if o[0].lower()=='zone' and 'plenum' not in o[1].lower()]
    plenums=[o[1].upper() for o in obs if o[0].lower()=='zone' and 'plenum' in o[1].lower()]
    ground=next(o for o in obs if o[0].lower()=='site:groundtemperature:buildingsurface')
    surfaces={o[1].upper():o for o in obs if o[0].lower()=='buildingsurface:detailed'}
    windows={z:[] for z in zones}
    for o in obs:
        if o[0].lower()=='fenestrationsurface:detailed':
            z=surfaces[o[4].upper()][4].upper()
            if z in windows: windows[z].append(o[1].upper())
    manual=set()
    for s in surfaces.values():
        z=s[4].upper()
        if z not in zones: continue
        target=s[7].upper()
        other=surfaces[target][4].upper() if s[6].lower()=='surface' and target in surfaces else target if s[6].lower()=='zone' else ''
        if other in zones and other!=z: manual.add(tuple(sorted((zones.index(z),zones.index(other)))))
    run=next(o for o in obs if o[0].lower()=='runperiod')
    return dict(zones=zones,plenums=plenums,ground_monthly_C=list(map(float,ground[1:13])),windows=windows,
                manual_edges=sorted(manual),simulation_start_weekday=run[8],
                zone_multipliers={o[1].upper():float(o[7]) for o in obs if o[0].lower()=='zone'})

def prepare_and_run(config, force=False):
    source=config.locate('.idf'); folder=config.output/'instrumented_energyplus';folder.mkdir(parents=True,exist_ok=True)
    original=source.read_text(encoding='utf-8-sig'); obs=objects(original)
    known={tuple(x.lower() for x in o) for o in obs}
    added=[]
    for name in VARIABLES:
        fields=['Output:Variable','*',name,'Timestep']
        if tuple(x.lower() for x in fields) not in known: added.append(','.join(fields)+';')
    # End-of-system-timestep Zone Air Temperature assists temporal audits when available;
    # the pipeline intentionally fits consistently reported mean zone temperatures.
    if not any(o[0].lower()=='output:sqlite' for o in obs): added.append('Output:SQLite,SimpleAndTabular;')
    candidate=original+'\n! RC identification instrumentation: reporting additions only.\n'+'\n'.join(added)+'\n'
    idf=folder/'instrumented.idf'; idf.write_text(candidate,encoding='utf-8')
    assert objects(candidate)[:len(obs)]==obs
    weather=config.locate('.epw')
    provenance=dict(source=str(source),source_sha256=digest(source),weather_sha256=digest(weather),
                    instrumented_sha256=digest(idf),energyplus=str(config.energyplus),added_requests=added)
    marker=folder/'provenance.json';out=folder/'run';sql=out/'eplusout.sql'
    if not force and marker.exists() and sql.exists() and json.loads(marker.read_text())==provenance:
        return sql,metadata(source)
    command=[str(config.energyplus),'-w',str(weather),'-d',str(out),str(idf)]
    proc=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    (folder/'console.txt').write_text(proc.stdout)
    err=(out/'eplusout.err').read_text() if (out/'eplusout.err').exists() else ''
    if proc.returncode or 'EnergyPlus Completed Successfully' not in err or '** Severe **' in err:
        raise RuntimeError(f'Instrumented EnergyPlus failed; inspect {folder}/console.txt and run/eplusout.err')
    marker.write_text(json.dumps(provenance,indent=2))
    return sql,metadata(source)
