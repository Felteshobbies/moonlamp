# Models

**The STL files in this folder are not in git.** Together they are about
1.3 GB, and four of them exceed GitHub's hard 100 MB limit for a single file.
Git LFS would not help either: the free allowance is 1 GB of storage and 1 GB
of traffic per month, which a handful of clones would exhaust.

So the binaries are distributed through Printables, and this repository carries
the scripts that regenerate them.

## What goes where

| Folder | Contents | Where it comes from |
|---|---|---|
| `upstream/` | `full.stl`, `moon-part-1..4.stl`, `Circle V1`, `Circle V2`, `Back support V1` | Downloaded from [Printables 1015789](https://www.printables.com/model/1015789-illuminated-moon-wall-lamp-remix) |
| `generated/` | `full_domed_H20_konisch*.stl` and the split parts | Produced by `tools/`, see below |
| `slicer/` | `moon-half*.3mf` | PrusaSlicer projects for the earlier flat relief |

## Regenerating everything

You need `upstream/full.stl` from the Printables page above. Then:

```bat
REM 1. dome the flat relief -- about a minute, 3,533,616 triangles unchanged
python tools\dome_moon.py --height 20 --cone 1 --cone-power 1.3 --apex 0.08 ^
       --in models\upstream\full.stl ^
       --out models\generated\full_domed_H20_konisch.stl

REM 2. pocket for the electronics, cable channels, and the splits
blender --background --python tools\blender_split.py -- --plug-radius 2.5

REM 3. verify
python tools\check_stl.py models\generated\full_domed_H20_konisch.stl
```

Step 2 needs Blender (tested with 5.2) and produces:

| File | Bounding box | Purpose |
|---|---|---|
| `*_box.stl` | 416.5 × 416.5 mm | The whole domed relief with the pocket and channels |
| `*_half1/2.stl` | 355.4 × 355.4 mm | Two halves, rotated 45°, for a 360 × 360 bed |
| `*_quarter1..4.stl` | 294.3 × 208.2 mm | Four quarters for smaller printers |

The pocket is 60 × 60 × 3 mm, centred on the underside. Two 4 × 4 mm cable
channels cross it at 90°, with 30° flanks so they print without support.

## Printing notes

* The back stays flat on the bed — no supports needed anywhere.
* Drop the infill to **5–8 %**. The dome adds roughly 1090 cm³ of enclosed
  volume that carries no load; at 15 % that is several hundred grams of PLA and
  many extra hours per part.
* The XY outline is unchanged from the original, so the frame still fits.

## License

These models are derived work under **CC BY-NC-SA 4.0**. See
[LICENSE-MODELS.md](../LICENSE-MODELS.md) for the attribution chain and what
the license requires of you.
