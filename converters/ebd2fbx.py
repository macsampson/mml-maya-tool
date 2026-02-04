#!/usr/bin/env python3

"""
mml_ebd2fbx - Convert Mega Man Legends EBD model files to FBX format with skeleton

Exports models with proper bone hierarchies for use in 3D software.
Uses ASCII FBX format (FBX 7.4) which doesn't require the Autodesk SDK.
"""

__version__ = "1.0"

import sys
import os


from MML.parsers.ebd_reader import EBDReader
from .fbx_exporter import FBXExporter


def usage():
    print(f"mml_ebd2fbx v{__version__} - Convert MML EBD models to FBX with skeleton")
    print(
        f"Usage: {os.path.basename(sys.argv[0])} [options] <input.ebd> [output.fbx] [model_index]"
    )
    print(f"")
    print(f"Options:")
    print(f"  -a, --all    Export all models as separate FBX files")
    print(f"")
    print(f"Arguments:")
    print(f"  input.ebd    Input EBD file")
    print(f"  output.fbx   Output FBX file (default: input name with .fbx extension)")
    print(f"  model_index  Which model to export (default: 0, ignored with -a)")
    sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        usage()

    # Parse arguments
    export_all = False
    args = []
    for arg in sys.argv[1:]:
        if arg in ("-a", "--all"):
            export_all = True
        else:
            args.append(arg)

    if not args:
        usage()

    input_file = args[0]
    base_name = os.path.splitext(input_file)[0]

    try:
        print(f"Reading {input_file}...")
        ebd = EBDReader(input_file)

        print(f"\nFound {len(ebd.models)} models")
        for i, model in enumerate(ebd.models):
            total_verts = sum(len(limb["vertices"]) for limb in model["limbs"])
            total_tris = sum(len(limb["triangles"]) for limb in model["limbs"])
            total_quads = sum(len(limb["quads"]) for limb in model["limbs"])
            print(
                f"  Model {i}: {len(model['limbs'])} limbs, {total_verts} vertices, "
                f"{total_tris} tris, {total_quads} quads"
            )

        exporter = FBXExporter()

        if export_all:
            print(f"\nExporting all {len(ebd.models)} models...")
            for i in range(len(ebd.models)):
                output_file = f"{base_name}_model{i}.fbx"
                print(f"\nExporting model {i}...")
                exporter.export(ebd, output_file, i)
            print(f"\nDone! Exported {len(ebd.models)} models.")
        else:
            output_file = args[1] if len(args) > 1 else base_name + ".fbx"
            model_index = int(args[2]) if len(args) > 2 else 0
            print(f"\nExporting model {model_index}...")
            exporter.export(ebd, output_file, model_index)

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


