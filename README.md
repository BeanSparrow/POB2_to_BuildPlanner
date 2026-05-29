# PoB2 → PoE2 Build Planner

Converts [Path of Building (PoE2)](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2) share codes into `.build` files that the in-game Path of Exile 2 Build Planner loads automatically.

## Setup

1. Clone this repo.

2. Download the official PoE2 passive tree data from [grindinggear/poe2-skilltree-export](https://github.com/grindinggear/poe2-skilltree-export/tree/main). Place the `data.json` file at:
   ```
   ggg_data/data.json
   ```

3. Copy `.env.example` to `.env` and set `POE2_BUILD_DIR` to your in-game Build Planner directory.
   - Windows default: `C:/Users/<YourName>/Documents/My Games/Path of Exile 2/BuildPlanner`
   - SteamOS default: see `.env.example`

## Usage

1. Open your build in Path of Building (PoE2).

2. Click **Generate** under Import/Export. Copy the share code and paste it into a `.pob` file under `pob_raw/`. The filename becomes the build name shown in-game.
   ```
   pob_raw/MyBuild_Act1.pob
   pob_raw/MyBuild_Endgame.pob
   ```

3. Run:
   ```
   python pob_to_build.py
   ```

4. One `.build` file is written per input into your configured `POE2_BUILD_DIR`. Launch the game and the planner activates automatically.

PoB only exports the currently-selected loadout (active tree spec, skill set, and item set). To export multiple variants from a single build, switch the active loadout in PoB, hit Generate again, and save each code to its own `.pob` file.
