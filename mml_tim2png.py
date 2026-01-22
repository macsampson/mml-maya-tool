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
    """Read MML container format TIM file or raw TIM file and return image."""

    with open(filepath, "rb") as f:
        data = f.read()

    # Check minimum size
    if len(data) < 20:
        raise ValueError("File too small to be valid TIM")

    # Detect file format: MML container (type=1) vs raw TIM (magic=0x10)
    first_dword = struct.unpack('<I', data[0x00:0x04])[0]
    
    if first_dword == 0x10:
        # Raw TIM file - TIM magic is at offset 0
        print("Detected: Raw TIM file (no MML container)")
        return read_raw_tim(data)
    elif first_dword == 1:
        # MML container format
        print("Detected: MML container TIM")
        return read_mml_container_tim(data)
    else:
        raise ValueError(f"Unknown file format: first dword = 0x{first_dword:08X}")


def read_raw_tim(data):
    """Parse a raw TIM file (standard PS1 TIM format)."""
    
    # TIM header
    tim_magic = struct.unpack('<I', data[0x00:0x04])[0]
    tim_flags = struct.unpack('<I', data[0x04:0x08])[0]
    
    if tim_magic != 0x10:
        raise ValueError(f"Invalid TIM magic: 0x{tim_magic:08X}")
    
    pMode = tim_flags & 7
    hasClut = (tim_flags >> 3) & 1
    
    print(f"TIM flags: pMode={pMode}, hasClut={hasClut}")
    
    offset = 8
    palette = []
    
    if hasClut:
        # Read CLUT header
        clut_size = struct.unpack('<I', data[offset:offset+4])[0]
        clut_x = struct.unpack('<H', data[offset+4:offset+6])[0]
        clut_y = struct.unpack('<H', data[offset+6:offset+8])[0]
        clut_w = struct.unpack('<H', data[offset+8:offset+10])[0]
        clut_h = struct.unpack('<H', data[offset+10:offset+12])[0]
        
        print(f"CLUT: {clut_w}x{clut_h} colors at ({clut_x},{clut_y})")
        
        # Read palette colors
        palette_offset = offset + 12
        num_colors = clut_w * clut_h
        for i in range(min(num_colors, 256)):
            if palette_offset + i*2 + 2 <= len(data):
                color = struct.unpack('<H', data[palette_offset + i*2:palette_offset + i*2 + 2])[0]
                r, g, b = convert_abgr_to_rgb(color)
                palette.extend([r, g, b])
        
        offset += clut_size
    
    # Read pixel data header
    pixel_size = struct.unpack('<I', data[offset:offset+4])[0]
    img_x = struct.unpack('<H', data[offset+4:offset+6])[0]
    img_y = struct.unpack('<H', data[offset+6:offset+8])[0]
    img_w = struct.unpack('<H', data[offset+8:offset+10])[0]  # Width in 16-bit words
    img_h = struct.unpack('<H', data[offset+10:offset+12])[0]
    
    # Calculate actual pixel width based on color depth
    if pMode == 0:  # 4-bit
        width = img_w * 4
    elif pMode == 1:  # 8-bit
        width = img_w * 2
    else:  # 16-bit or 24-bit
        width = img_w
    
    height = img_h
    print(f"Image: {width}x{height} pixels (pMode={pMode})")
    
    pixel_offset = offset + 12
    pixel_data = data[pixel_offset:]
    
    # Raw TIM files use simple linear pixel layout
    if pMode == 0:  # 4-bit
        expanded = bytearray()
        for byte in pixel_data:
            pix0 = byte & 0x0F
            pix1 = (byte >> 4) & 0x0F
            expanded.append(pix0)
            expanded.append(pix1)
        
        needed = width * height
        if len(expanded) > needed:
            expanded = expanded[:needed]
        elif len(expanded) < needed:
            expanded.extend([0] * (needed - len(expanded)))
        
        image = Image.frombytes("P", (width, height), bytes(expanded), "raw", "P", 0, 1)
        if palette:
            image.putpalette(palette)
            
    elif pMode == 1:  # 8-bit
        needed = width * height
        expanded = pixel_data[:needed]
        if len(expanded) < needed:
            expanded = expanded + bytes(needed - len(expanded))
        
        image = Image.frombytes("P", (width, height), bytes(expanded), "raw", "P", 0, 1)
        if palette:
            image.putpalette(palette)
    else:
        raise ValueError(f"Unsupported pMode: {pMode}")
    
    return image


def read_mml_container_tim(data):
    """Parse an MML container TIM file - matches TIMFile.cs from DashViewer."""
    
    if len(data) < 0x800:
        raise ValueError("File too small to be valid MML TIM container")

    # Read header fields - matching TIMFile.cs offsets exactly
    # ColorsPerPalette at ofs + 0x14
    # PaletteCount at ofs + 0x18
    # ImageX at ofs + 0x1C
    # ImageY at ofs + 0x20
    # ImageWidth at ofs + 0x24
    # ImageHeight at ofs + 0x28
    
    colors_per_palette = struct.unpack('<I', data[0x14:0x18])[0]
    palette_count = struct.unpack('<I', data[0x18:0x1C])[0]
    image_x = struct.unpack('<I', data[0x1C:0x20])[0]
    image_y = struct.unpack('<I', data[0x20:0x24])[0]
    image_width = struct.unpack('<I', data[0x24:0x28])[0]
    image_height = struct.unpack('<I', data[0x28:0x2C])[0]

    print(f"ColorsPerPalette: {colors_per_palette}, PaletteCount: {palette_count}")
    print(f"ImagePos: ({image_x}, {image_y}), Size: {image_width}x{image_height} (raw)")

    # If no image dimensions, this is a palette-only file
    if image_width == 0 or image_height == 0:
        raise ValueError("No image data (palette-only file)")

    # Read palettes from offset 0x100
    palettes = []
    if colors_per_palette != 0 and palette_count != 0:
        pal_offset = 0x100
        for i in range(palette_count):
            palette = []
            for j in range(colors_per_palette):
                if pal_offset + 2 <= len(data):
                    color = struct.unpack('<H', data[pal_offset:pal_offset + 2])[0]
                    r, g, b = convert_abgr_to_rgb(color)
                    palette.extend([r, g, b])
                    pal_offset += 2
            palettes.append(palette)
    
    # Use first palette
    palette = palettes[0] if palettes else []

    # Calculate actual pixel dimensions based on color depth
    # From TIMFile.cs: imgw *= 4 for 16-color, imgw *= 2 for 256-color
    if colors_per_palette == 16:
        imgw = image_width * 4
        imgh = image_height
        block_width = 128
        block_height = 32
    elif colors_per_palette == 256:
        imgw = image_width * 2
        imgh = image_height
        block_width = 64  # 128 / 2
        block_height = 32
    else:
        raise ValueError(f"Unsupported color depth: {colors_per_palette}")

    print(f"Output: {imgw}x{imgh} pixels ({colors_per_palette} colors)")

    # Extract pixel data (starts at 0x800)
    pixel_data = data[0x800:]

    # Create image using block-based decoding (matching TIMFile.cs ReloadImage)
    image = Image.new('P', (imgw, imgh))
    pixels = image.load()
    
    rofs = 0
    
    if colors_per_palette == 16:
        # 4-bit: 2 pixels per byte, iterate bx += 2
        for y in range(0, imgh, block_height):
            for x in range(0, imgw, block_width):
                for by in range(block_height):
                    for bx in range(0, block_width, 2):
                        if rofs >= len(pixel_data):
                            break
                        
                        byte = pixel_data[rofs]
                        idx1 = byte & 0x0F
                        idx2 = (byte >> 4) & 0x0F
                        
                        px1, py = x + bx, y + by
                        px2 = x + bx + 1
                        
                        if px1 < imgw and py < imgh:
                            pixels[px1, py] = idx1
                        if px2 < imgw and py < imgh:
                            pixels[px2, py] = idx2
                        
                        rofs += 1
    else:
        # 8-bit: 1 pixel per byte
        for y in range(0, imgh, block_height):
            for x in range(0, imgw, block_width):
                for by in range(block_height):
                    for bx in range(block_width):
                        if rofs >= len(pixel_data):
                            break
                        
                        byte = pixel_data[rofs]
                        px, py = x + bx, y + by
                        
                        if px < imgw and py < imgh:
                            pixels[px, py] = byte
                        
                        rofs += 1

    # Apply palette
    if palette:
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

