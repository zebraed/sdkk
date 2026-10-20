<p align="center">
  <img src="ui/resources/sdkk.svg" alt="SDKK" width="96">
</p>

# SDKK

A Set Driven Key tool for Maya. Pose on the timeline or in the viewport, key it with one button, and manage, mirror, export, and import driven keys without opening the Graph Editor.

## Description

SDKK builds and manages driven keys (SDK) from a single window.

- **Setup**: pick a driver, add the driven nodes, and key the current pose at the current driver value. A pose strip shows every keyed driver value, so you can scrub, move, and delete keys directly.
- **I/O**: export the driven keys of selected nodes (or the whole scene) to a JSON file, and import them back, even onto a character with different names.
- **Mirror**: copy driven keys to the opposite side by a name rule (for example `_L` to `_R`), with per-key control over inverting the driver axis and the value.
- **Advanced**: convert animation keyed on the timeline into driven keys.

Every operation is a single undo step, and every GUI action prints the equivalent Python command to the Script Editor, so you can turn a manual workflow into a script.

## Requirements

| Item | Notes |
| --- | --- |
| **Maya** | 2023 or later (Python 3.9+). |
| **Qt.py** | Bundled in `vendor/` (2.0.7). Nothing to install. |

## Installation

1. Copy this repository into a folder named `sdkk` in your Maya scripts directory.

   - Windows: `%USERPROFILE%\Documents\maya\scripts\sdkk`
   - macOS: `~/Library/Preferences/Autodesk/maya/scripts/sdkk`
   - Linux: `~/maya/scripts/sdkk`

2. Restart Maya.

If you keep the folder somewhere else, add its parent directory to the Python path instead.

```python
import sys
sys.path.insert(0, r"/path/to/parent_of_sdkk")
```

## Usage

Open the window from the Script Editor (Python tab).

```python
import sdkk
sdkk.show()
```

Opening the window again closes the previous one and opens a new one.

### Setup

The **Setup** tab creates driven keys. The **pose area** at the bottom of the window (pose strip, presets, **Driven Edit**, and the key button) is always visible, whichever tab is open.

1. **Set the driver.** Select the driver node in Maya and press **Set Selected**, then choose the driver attribute: one of the nine transform attributes (TX to SZ), or any other attribute through **Other**. Attributes that already drive a driven key are marked.
2. **Add the driven nodes.** Select the nodes in Maya and press **+ Add**. Click a row in the table to edit that node's attributes.
3. **Choose the driven attributes.** Toggle the transform cells (TX to SZ) of the selected node, or use **Other** for any other attribute.
   - A cell with an orange border is enabled (it is keyed together with the others).
   - Amber fill: the attribute is already driven by the current driver.
   - Blue-gray fill: the attribute is driven by another driver.
   - A cell that cannot be keyed (locked, missing, or already connected to something else) is disabled, and the reason is shown in its tooltip.
4. **Move the driver and pose the driven nodes.** Drag on the pose strip, or use the preset buttons. A preset button adds its number to the driver (the `0` button sets the driver to 0). Middle-click a preset button to edit its number.
5. **Press the key button.** It keys every enabled driven attribute of the selected rows (or the displayed node if no row is selected) at the current driver value. The button reads **SET KEY**, **SET / UPDATE KEY**, or **UPDATE KEY** depending on how many attributes already have a key there.

**Driven Edit** keeps the driven nodes in their current pose while you move the driver with the strip or the presets. Use it to key the held pose at a new driver value.

#### The pose strip

| Action | Result |
| --- | --- |
| Left-drag | Scrubs the driver. The value snaps to a nearby key; hold **Shift** for steps of 0.1. |
| Middle-drag a key | Moves that key between its neighbours. The first and last keys can be dragged outward. Hold **Shift** for steps of 0.1. |
| Right-click a key | **Delete Key** removes the keys at that driver value. |

A filled diamond is a key on every attribute, a hollow diamond with a dot is a key on some attributes, and the triangle is the current driver value.

#### Right-click menus

Right-click a driven node row, a transform cell, or an entry in the **Other** list for:

- **Select Anim Curve**: selects the animCurve (and blendWeighted) nodes in Maya.
- **Delete Current Driver Key**: deletes the keys of the current driver on that attribute.
- **Delete All Keys on Attribute**: deletes every driven key on that attribute, from every driver. A confirmation dialog appears first.
- **Remove Item**: removes the node or attribute from the setup (it does not touch the scene). Available on node rows and on entries of the **Other** list.

#### History

The **History** menu lists the driver and driven sets you have worked with, newest first. Pick one to restore it on the Setup tab. Nodes that no longer exist are reported in the status bar.

### I/O

The **I/O** tab exports and imports driven keys as JSON. **Tools > Export Driven Key...** and **Tools > Import Driven Key...** open the same two sections as separate windows, so you can keep them next to the main window.

**Export**

1. Choose **Driver** or **Driven** to say what the nodes you load are.
2. Press **Load from Selection** (selected nodes that have driven keys) or **Load from Scene** (every node that has driven keys).
3. Check the nodes to export and press **Export...**. The driven keys that those nodes drive (or are driven by) are written to the file.

**Import**

1. Press **Open File...** and choose a JSON file. Its driven keys are listed, and the ones that can be applied are checked.
2. Set **If it exists**: **Replace** rebuilds a driven key that already exists in the scene; **Skip** leaves it alone.
3. Turn on **Unlock locked driven** to apply to locked attributes (they are unlocked while applying and locked again afterwards).
4. Press **Import**.

The **Status** column and its tooltip explain why an item cannot be applied (for example, the node is missing, the attribute is locked, or the attribute already has another input). The scene units are switched to the file's units while importing, then restored.

### Mirror

The **Mirror** tab copies driven keys to the opposite side by a name rule.

1. Set the rule under **RULE**.
   - **Search** and **Replace**: the text in node names to replace, and what to replace it with. Only driven keys whose names contain the Search text are listed. The arrow button swaps the two fields.
   - **Regex**: use Search as a regular expression and Replace as its replacement.
   - **Invert Value**: the driven attributes whose values are negated by default (for example `TX`).
   - **Invert Driver**: the driver attributes whose input axis is negated by default.
2. Under **TARGETS**, choose **Driver** or **Driven**, then press **Load from Selection** or **Load from Scene**.
3. Review the table. Each row shows the source, the mirrored result, and a status. **Inv Driver** and **Inv Value** can be changed per row, and a changed flag stays with that driven key.
4. Check the rows to mirror and press **Mirror**. Rows that are `not_mirrored` or `different` are checked automatically.

| Status | Meaning |
| --- | --- |
| `ok` | The mirrored side already matches. |
| `not_mirrored` | The mirrored node exists but has no driven key. |
| `different` | The mirrored driven key differs from the mirrored result. The tooltip shows the first differences. |
| `missing` | The mirrored driver or driven node does not exist. |
| `blocked` | The mirrored side cannot be checked (ambiguous name, type mismatch, an unreadable curve). |
| `unmirrorable` | The rule cannot be applied (for example, inverting the driver axis of a curve with step tangents). |

### Advanced

The **Advanced** tab converts animation keyed on the timeline into driven keys, so you can pose on the timeline instead of building curves in the Graph Editor.

1. In **Setup**, set the driver and add the driven nodes.
2. Animate the driven nodes on the timeline while the driver moves through the values you want.
3. On **Advanced**, press **Load Animation**. The animated attributes of the driven nodes are listed with their key counts and driver range.
4. Check the attributes and press **Convert to Driven Key**. The timeline animation of the converted attributes is deleted.

The driver has to keep increasing or decreasing across the keys. A motion that returns to the same driver value cannot become a driven key, and that row is reported as an error.

### Options

| Option | Description |
| --- | --- |
| **Select Node on Row Click** | Clicking a row in a table selects its node in Maya. |
| **Unlock Locked Driven on Apply** | Locked driven attributes are unlocked while keys are applied, then locked again. |
| **Language** | **English** or **日本語**. The choice is remembered. |

The window size, the options, the presets, the mirror rule, and the history are saved between sessions.

### Script

Everything the GUI does is available from Python through `import sdkk`. The Script Editor shows the exact call for each GUI action.

```python
import sdkk

# Key a driver/driven pair
sdkk.set_driven_key(
    "jaw_ctl.rotateX",
    "lip_L_jnt.translateY",
    [0.0, 15.0, 30.0],
    [0.0, -0.5, -1.5],
)

# Key the current values of several driven attributes at the driver's current value
sdkk.set_driven_keys("jaw_ctl.rotateX", ["lip_L_jnt.translateY", "lip_L_jnt.translateZ"])

# Mirror driven keys by a name rule
sdkk.mirror_driven_keys(
    ["lip_L_jnt"],
    role=1,                      # 1: the nodes are driven nodes (0: driver nodes)
    search="_L",
    replace="_R",
    invert_driven=["translateX"],
)

# Export and import
sdkk.export_driven_keys("path/to/face_sdk.json", ["jaw_ctl"])
sdkk.import_driven_keys("path/to/face_sdk.json")

# Convert timeline animation into driven keys
sdkk.convert_animation_to_driven_keys("arm_jnt.rotateZ", ["deltoid_jnt"])

# Delete driven keys, and clean up broken ones (dry run by default)
sdkk.delete_driven_keys("lip_L_jnt")
sdkk.cleanup_driven_keys()
```

## License

[MIT License](LICENSE)

sdkk bundles [Qt.py](https://github.com/mottosso/Qt.py) (MIT License, Copyright (c) 2016 Marcus Ottosson) in `vendor/`. Its license is in [vendor/Qt.py.LICENSE](vendor/Qt.py.LICENSE).
