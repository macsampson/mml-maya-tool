#!/usr/bin/env python3

#
# mml_tim2png - Convert Mega Man Legends TIM container to PNG format
#
# This handles the custom container format used in MML where TIM data
# is wrapped with a header containing metadata.
#
# Container Structure:
#   0x000-0x0FF: Container header (256 bytes)
#       0x00: Type (always 1)
#       0x04: Data size
#       0x0C: Image width (pixels)
#       0x10: Image height (pixels)
#       0x14: TIM magic (0x10)
#       0x18: TIM flags (pMode | hasClut << 3)
#       0x40: Original filepath string
#   0x100-0x1FF: CLUT data (256 bytes = 8 palettes x 16 colors)
#   0x200-0x7FF: Padding (zeros)
#   0x800-end:   Pixel data (4-bit indexed)
#

__version__ = "1.0"

import sys
import os
import struct

from PIL import Image


def convert_abgr_to_rgb(color_16bit):
    """Convert 16-bit ABGR (PlayStation format) to RGB tuple."""
    r = (color_16bit & 0x1F) << 3
    g = ((color_16bit >> 5) & 0x1F) << 3
    b = ((color_16bit >> 10) & 0x1F) << 3
    # Expand 5-bit to 8-bit properly
    r = r | (r >> 5)
    g = g | (g >> 5)
    b = b | (b >> 5)
    return (r, g, b)


def read_mml_tim(filepath):
    """Read MML container format TIM file and return image."""

    with open(filepath, "rb") as f:
        data = f.read()

    # Check minimum size
    if len(data) < 0x800:
        raise ValueError("File too small to be valid MML TIM container")

    # Check container type
    container_type = struct.unpack('<I', data[0x00:0x04])[0]
    if container_type != 1:
        raise ValueError(f"Unknown container type: {container_type}")

    # Read header fields
    data_size = struct.unpack('<I', data[0x04:0x08])[0]
    width = struct.unpack('<I', data[0x0C:0x10])[0]
    height = struct.unpack('<I', data[0x10:0x14])[0]
    tim_magic = struct.unpack('<I', data[0x14:0x18])[0]
    tim_flags = struct.unpack('<I', data[0x18:0x1C])[0]

    # Verify TIM magic
    if tim_magic != 0x10:
        raise ValueError(f"Invalid TIM magic: 0x{tim_magic:08X}")

    # Parse TIM flags
    pMode = tim_flags & 7
    hasClut = (tim_flags >> 3) & 1

    if pMode != 0:
        raise ValueError(f"Only 4-bit mode supported, got pMode={pMode}")
    if not hasClut:
        raise ValueError("Expected CLUT but flag not set")

    print(f"Container: type={container_type}, size={data_size}")
    print(f"Image: {width}x{height}, 4-bit indexed with CLUT")

    # Extract CLUT (8 palettes of 16 colors at offset 0x100)
    clut_offset = 0x100
    clut_size = 256  # 8 palettes * 16 colors * 2 bytes

    # Read first palette (16 colors)
    palette = []
    for i in range(16):
        color = struct.unpack('<H', data[clut_offset + i*2:clut_offset + i*2 + 2])[0]
        r, g, b = convert_abgr_to_rgb(color)
        palette.extend([r, g, b])

    # Extract pixel data (starts at 0x800)
    pixel_offset = 0x800
    pixel_data = data[pixel_offset:]

    # Calculate actual dimensions from pixel data
    pixel_count = len(pixel_data) * 2  # 4-bit = 2 pixels per byte

    # Use header dimensions if they make sense, otherwise calculate
    if width * height * 2 <= pixel_count:
        # Header dimensions might describe one frame
        # Check if data suggests multiple frames
        actual_height = pixel_count // width
        if actual_height != height:
            print(f"Note: Header says {height} rows, but data has {actual_height} rows")
            print(f"      This might be a sprite sheet with multiple frames")
        height = actual_height

    print(f"Output: {width}x{height} pixels")

    # Expand 4-bit pixels to 8-bit
    expanded = bytearray()
    for byte in pixel_data:
        pix0 = byte & 0x0F
        pix1 = (byte >> 4) & 0x0F
        expanded.append(pix0)
        expanded.append(pix1)

    # Trim to exact size needed
    needed = width * height
    if len(expanded) > needed:
        expanded = expanded[:needed]
    elif len(expanded) < needed:
        # Pad with zeros if needed
        expanded.extend([0] * (needed - len(expanded)))

    # Create image
    image = Image.frombytes("P", (width, height), bytes(expanded), "raw", "P", 0, 1)

    # Apply palette
    image.putpalette(palette)

    return image


def read_mml_tim_all_palettes(filepath):
    """Read MML TIM and return images for all 8 palettes."""

    with open(filepath, "rb") as f:
        data = f.read()

    if len(data) < 0x800:
        raise ValueError("File too small")

    width = struct.unpack('<I', data[0x0C:0x10])[0]

    # Extract pixel data
    pixel_offset = 0x800
    pixel_data = data[pixel_offset:]
    pixel_count = len(pixel_data) * 2
    height = pixel_count // width

    # Expand 4-bit pixels
    expanded = bytearray()
    for byte in pixel_data:
        expanded.append(byte & 0x0F)
        expanded.append((byte >> 4) & 0x0F)
    expanded = expanded[:width * height]

    images = []

    # Create image for each palette
    for pal_idx in range(8):
        clut_offset = 0x100 + pal_idx * 32
        palette = []
        for i in range(16):
            color = struct.unpack('<H', data[clut_offset + i*2:clut_offset + i*2 + 2])[0]
            r, g, b = convert_abgr_to_rgb(color)
            palette.extend([r, g, b])

        image = Image.frombytes("P", (width, height), bytes(expanded), "raw", "P", 0, 1)
        image.putpalette(palette)
        images.append(image)

    return images


def usage(exitcode, error=None):
    print("Usage: %s [OPTION...] <input.tim> [<output.png>]" % os.path.basename(sys.argv[0]))
    print("  -a, --all-palettes          Export all 8 palette variations")
    print("  -V, --version               Display version information and exit")
    print("  -?, --help                  Show this help message")
    print()
    print("This tool handles the MML container format where TIM data is wrapped")
    print("with a custom header. Standard TIM files should use tim2png.py instead.")

    if error is not None:
        print("\nError:", error, file=sys.stderr)

    sys.exit(exitcode)

if __name__ == "__main__":
    # Parse command line arguments
    inputFileName = None
    outputFileName = None
    allPalettes = False

    for arg in sys.argv[1:]:
        if arg == "--version" or arg == "-V":
            print("mml_tim2png", __version__)
            sys.exit(0)
        elif arg == "--help" or arg == "-?":
            usage(0)
        elif arg == "--all-palettes" or arg == "-a":
            allPalettes = True
        elif arg[0] == "-":
            usage(64, "Invalid option '%s'" % arg)
        else:
            if inputFileName is None:
                inputFileName = arg
            elif outputFileName is None:
                outputFileName = arg
            else:
                usage(64, "Unexpected extra argument '%s'" % arg)

    if inputFileName is None:
        usage(64, "No input file specified")
    if outputFileName is None:
        outputFileName = os.path.splitext(inputFileName)[0] + ".png"

    # Process file
    try:
        if allPalettes:
            images = read_mml_tim_all_palettes(inputFileName)
            base, ext = os.path.splitext(outputFileName)
            for i, img in enumerate(images):
                outpath = f"{base}_pal{i}{ext}"
                img.save(outpath, "PNG")
                print(f"Written '{outpath}'")
        else:
            image = read_mml_tim(inputFileName)
            image.save(outputFileName, "PNG")
            print(f"Written '{outputFileName}'")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

