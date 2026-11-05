# Medium Office: lithium-ion NMC replacement

The active NMC scenarios are `RefBldgMediumOfficeNew2004_Chicago_PV60_NMC.idf` and `RefBldgMediumOfficeNew2004_Chicago_PV80_NMC.idf`. Historical KiBaM models/results are retained. The NMC models use `ElectricLoadCenter:Storage:LiIonNMCBattery` in EnergyPlus 25.2.0, with the existing DC-coupled inverter and surplus-following native dispatch. No storage losses are injected into building thermal zones. Semantic checks confirm unchanged HVAC, geometry, schedules and PV objects.

## Parameters and rationale

| Quantity | Value | Basis |
|---|---:|---|
| Roof area | 1660.7286 m2 | Inherited building geometry |
| Active PV cell fractions | 60%, 80% | Existing sensitivity scenarios; not a verified rooftop layout |
| Active PV cell areas | 996.4372, 1328.5829 m2 | Roof area times active fraction |
| PV conversion efficiency | 20% | Existing Simple PV scenario assumption |
| Nominal PV output at 1 kW/m2 | 199.2874, 265.7166 kWp DC | Active area times conversion efficiency |
| Inverter efficiency | 96% | Unchanged Simple inverter assumption |
| Battery cells in series / parallel strings | 139 / 139 | Retain example series voltage; choose parallel count to match the previous capacity |
| Nominal cell voltage / cell capacity | 3.342 V / 3.2 Ah | Explicit EnergyPlus 25.2 IDD defaults |
| Nominal pack voltage / charge capacity | 464.538 V / 444.8 Ah | Series and parallel scaling |
| Nominal pack energy | 206.6265 kWh | Voltage times Ah; previous KiBaM scenario was 206.64 kWh |
| Charge / discharge design requests | 50 / 50 kW DC | Unchanged approximately four-hour nameplate sizing; not an economic optimum |
| Initial input SOC | 20% | Unchanged; post-warmup reported SOC is 24% |
| Native dispatch SOC bounds | 24% to 94% | Unchanged load-centre inputs |
| MPC planning SOC bounds | 24% to 92% | Unchanged controller reserve/headroom |
| DC-to-DC charging efficiency input | 95% | EnergyPlus default; not a measured round-trip efficiency |
| Pack mass / heat-transfer area | 1901.52 kg / 23.6856 m2 | Scale the installed NMC example's 342 kg / 4.26 m2 by 139/25 |
| Specific heat / heat-transfer coefficient | 1500 J/(kg K) / 7.5 W/(m2 K) | EnergyPlus defaults |
| Full / exponential-end / nominal-end cell voltage | 4.2 / 3.53 / 3.342 V | EnergyPlus defaults |
| Exponential-end / nominal-end removed-capacity fractions | 0.8075 / 0.976875 | EnergyPlus defaults |
| Voltage-curve reference charge rate / cell resistance | 1 / 0.09 ohm | EnergyPlus defaults |
| Lifetime model | KandlerSmith | Built-in NMC option; ageing estimates are not manufacturer validated |

The reference is the **installed** `C:/EnergyPlusV25-2-0/ExampleFiles/ShopWithPVandLiIonBattery.idf`, which uses 139 series cells and 25 parallel strings, together with `Energy+.idd` defaults. Scaling mass and area linearly represents additional identical assemblies; it does not establish an actual cabinet design. This is a documented generic NMC simulation scenario, not a calibrated commercial battery installation. Hashes and sizing arithmetic are recorded in `manifest_nmc.json`.

## Validation and limitations

Both annual runs complete with zero severe errors and five inherited building/report warnings per run. Each contains 52,560 ten-minute records. Annual facility and inverter electrical balances pass, and HVAC demand and PV generation match their PV-only reference runs. Detailed battery outputs contain no simultaneous charge/discharge. See `verification_nmc.json` and each `runs/PV*_NMC/eplusout.err`.

**The nominal 50 kW power check does not pass in the annual native-dispatch runs:** achieved discharge reaches 50.479 kW (60% PV) and 50.559 kW (80% PV). The NMC implementation returns achieved power after its internal voltage/current calculation. These outputs are retained and the exceedance is flagged, rather than treating 50 kW as an exactly enforced physical rating. No EnergyPlus source changes or controller retuning were made. The separate August MPC comparisons meet the nominal-power check; July has a similar small native-dispatch exceedance, documented with those results.

Battery temperature is reported, but its annual range was only 20.0–24.33 C despite blank-zone/outdoor-loss placement. The EnergyPlus 25.2 source updates an ambient-temperature field on a copied state after setting the SSC battery state. Consequently, these results should not be used to validate outdoor-weather thermal response, low-temperature operating protection or battery lifetime. The generic battery model is used here for electrical-storage/control comparison. Enclosure conditioning and auxiliary electricity are not modeled.

SOC is a charge fraction. SOC multiplied by nominal kWh is the controller's approximate inventory measure, not exact stored electrochemical energy at varying voltage, temperature and capacity. Warmup moves the input 20% SOC to the native 24% lower limit. Annual first/final SOC are reported; MPC comparisons use common conditioning and recovery days and explicitly compare actual initial/final SOC.

The MPC retains its first-order scheduling model with assumed 90% charging and 90% discharging efficiencies. These are distinct from the detailed NMC plant and its 95% DC-to-DC input; they were held fixed to avoid combining a chemistry replacement with controller tuning. The observer for thermal disturbances does not estimate battery efficiency.

## Files and reproduction

- `annual_summary_nmc.csv`: annual native-control electrical results, not MPC savings.
- `PV60_NMC_timeseries.csv`, `PV80_NMC_timeseries.csv`: ten-minute outputs; corresponding monthly files are also saved.
- `build_nmc.py build`: generate the two NMC models from preserved KiBaM scenarios; `--source` selects their folder.
- `build_nmc.py run`: run both annual simulations; refuses to overwrite existing SQL results.
- `analyse_nmc.py`: reproduce annual summaries and separate balance/SOC and nominal-power audit outcomes.
- MPC outputs and the new review notebook are in `../../mpc/pv_bess_mpc`, under labels ending `_nmc`.

Run scripts with a Python environment containing NumPy, pandas and SciPy. The verified local runtime is `C:/Program Files/FreeCAD 1.0/bin/python.exe`. EnergyPlus is expected at `C:/EnergyPlusV25-2-0`.

## References

- [EnergyPlus 25.2 NMC input/output reference](https://bigladdersoftware.com/epx/docs/25-2/input-output-reference/group-electric-load-center-generator.html#electricloadcenterstorageliionnmcbattery).
- [EnergyPlus engineering reference supplied for this change](https://bigladdersoftware.com/epx/docs/22-2/engineering-reference/electric-load-center-distribution-manager.html).
- [EnergyPlus 25.2 implementation, simulateLiIonNmcBatteryModel](https://github.com/NREL/EnergyPlus/blob/v25.2.0/src/EnergyPlus/ElectricPowerServiceManager.cc).
