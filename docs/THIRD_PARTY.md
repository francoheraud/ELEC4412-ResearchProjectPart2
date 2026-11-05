# Sources and attribution

- Building: DOE commercial reference Medium Office, Chicago, new construction
  2004, distributed with EnergyPlus example files. Original attribution comments
  in the IDF are retained. Study additions are the PV and NMC battery objects,
  instrumentation and supervisory actuator schedules.
  https://www.energy.gov/cmei/buildings/commercial-reference-buildings
- Simulator and Python API: EnergyPlus 25.2. Install separately; the executable
  and its libraries are not part of this repository.
  https://energyplus.net/
- Weather: `USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw`, the supplied Chicago
  O'Hare typical-meteorological-year file. It is not actual August 2017 weather.
- Prices: the supplied full-year 2025 ComEd BES-H hourly energy-price CSV.
  Source landing page: https://www.comed.com/MyAccount/MyBillUsage/Pages/RatesPricing.aspx
  The original sequence, including negative values and timestamp-label
  irregularities, is preserved. Run protocols document the row-based mapping
  to the simulation calendar. This is an energy-price scenario, not a claim
  about actual export settlement or a full commercial tariff.
- Python numerical and plotting dependencies retain their respective upstream
  licences. Install them through `requirements.txt`; they are not vendored.

The research was developed with AI-assisted coding and writing support.
The thesis declaration describes the author's contribution and AI use. This
repository records executable methods and saved results; it does not imply
independent field verification or a new general MPC theory.
