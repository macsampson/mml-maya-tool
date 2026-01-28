
import struct

class EBDReader:
    """Read and parse EBD model files."""

    DATA_START = 0x800

    def __init__(self, filepath):
        with open(filepath, "rb") as f:
            self.data = f.read()

        # Read container header
        self.file_type = struct.unpack("<I", self.data[0x00:0x04])[0]
        self.data_size = struct.unpack("<I", self.data[0x04:0x08])[0]
        self.ram_address = struct.unpack("<I", self.data[0x0C:0x10])[0]

        # Read model count
        self.model_count = struct.unpack(
            "<I", self.data[self.DATA_START : self.DATA_START + 4]
        )[0]
        
        print(f"Header: Type={hex(self.file_type)}, Size={self.data_size}, RAM={hex(self.ram_address)}")
        print(f"Model Count: {self.model_count} at offset {hex(self.DATA_START)}")

        # Parse models
        self.models = []
        offset = self.DATA_START + 4
        for i in range(self.model_count):
            model = self.parse_model(offset)
            if model:
                self.models.append(model)
            offset += 16

    def ps1_to_file_offset(self, ps1_addr):
        """Convert PS1 memory address to file offset"""
        if ps1_addr == 0 or (ps1_addr >> 24) != 0x80:
            return None
        return (ps1_addr - self.ram_address) + self.DATA_START

    def read_int(self, offset):
        return struct.unpack("<I", self.data[offset : offset + 4])[0]

    def read_short(self, offset):
        return struct.unpack("<h", self.data[offset : offset + 2])[0]

    def read_ushort(self, offset):
        return struct.unpack("<H", self.data[offset : offset + 2])[0]

    def parse_model(self, offset):
        """Parse a model entry"""
        unknown1 = self.read_int(offset)
        limb_info_addr = self.read_int(offset + 4)
        hierarchy_addr = self.read_int(offset + 8)
        anim_order_addr = self.read_int(offset + 12)

        limb_info_start = self.ps1_to_file_offset(limb_info_addr)
        if limb_info_start is None:
            print(f"Invalid limb_info_addr: {hex(limb_info_addr)}")
            return None

        hierarchy_start = self.ps1_to_file_offset(hierarchy_addr)

        # Read LOD model addresses (at limb_info_start + 0x70)
        lod_offsets = []
        for i in range(3):
            addr_check = limb_info_start + 0x70 + i * 4
            if addr_check + 4 > len(self.data):
                 print(f"Read out of bounds at {hex(addr_check)}. Data len: {len(self.data)}")
                 break
            lod_addr = self.read_int(addr_check)
            lod_offset = self.ps1_to_file_offset(lod_addr)
            if lod_offset:
                lod_offsets.append(lod_offset)

        if not lod_offsets:
            return None

        # Parse LOD 0 (highest detail)
        lod_start = lod_offsets[0]
        limb_count = self.data[lod_start + 3]

        # Parse limb index entries (at limb_info_start + 0x10)
        limb_indices = []
        for i in range(limb_count):
            idx_offset = limb_info_start + 0x10 + i * 4
            render_idx = self.data[idx_offset]
            parent_idx = self.data[idx_offset + 1]
            bone_idx = self.data[idx_offset + 2]  # The actual bone index (childBone in JS)
            limb_indices.append(
                {
                    "render": render_idx,
                    "parent": parent_idx,
                    "bone_index": bone_idx,  # Renamed from 'translation' for clarity
                }
            )

        # Parse bone translations from hierarchy address
        bone_translations = []
        animations = []
        
        if hierarchy_start and (hierarchy_start >> 24) == 0:
            limb_trans_addr = self.read_int(hierarchy_start)
            first_anim_addr = self.read_int(hierarchy_start + 4)

            limb_trans_ofs = self.ps1_to_file_offset(limb_trans_addr)
            first_anim_ofs = self.ps1_to_file_offset(first_anim_addr)

            if limb_trans_ofs and first_anim_ofs and (first_anim_ofs >> 24) == 0:
                num_translations = (first_anim_ofs - limb_trans_ofs) // 8

                for i in range(num_translations):
                    t_offset = limb_trans_ofs + i * 8
                    if t_offset + 8 > len(self.data):
                        break
                    tx = self.read_short(t_offset)  # X is positive in DashViewer
                    ty = -self.read_short(t_offset + 2) # Y is negated
                    tz = -self.read_short(t_offset + 4) # Z is negated
                    bone_translations.append((tx, ty, tz))
                
                # Parse animations - pass hierarchy_start since anim table is at hierarchy_start+4
                animations = self.parse_animations(hierarchy_start, limb_count)

        # Parse limb information entries
        limbs = []
        limb_offset = lod_start + 0x14
        for i in range(limb_count):
            limb = self.parse_limb_info(limb_offset)
            if limb:
                limbs.append(limb)
            limb_offset += 20

        return {
            "limb_info_start": limb_info_start,
            "lod_offsets": lod_offsets,
            "limbs": limbs,
            "limb_indices": limb_indices,
            "bone_translations": bone_translations,
            "animations": animations,
        }

    def parse_limb_info(self, offset):
        """Parse a limb information entry (20 bytes)"""
        tri_count = self.data[offset]
        quad_count = self.data[offset + 1]
        vert_count = self.data[offset + 2]
        limb_number = self.data[offset + 3]

        tri_start = None
        if self.data[offset + 7] == 0x80:
            tri_start = self.ps1_to_file_offset(self.read_int(offset + 4))

        quad_start = None
        if self.data[offset + 11] == 0x80:
            quad_start = self.ps1_to_file_offset(self.read_int(offset + 8))

        texture_page = self.read_ushort(offset + 12)
        clut_page = self.read_ushort(offset + 14)

        vert_start = None
        if self.data[offset + 19] == 0x80:
            vert_start = self.ps1_to_file_offset(self.read_int(offset + 16))

        # Parse vertices
        vertices = []
        if vert_start and vert_count > 0:
            for i in range(vert_count):
                v_offset = vert_start + i * 8
                x = self.read_short(v_offset)
                y = -self.read_short(v_offset + 2)
                z = -self.read_short(v_offset + 4)
                vertices.append((x, y, z))

        # Parse triangles
        triangles = []
        if tri_start and tri_count > 0:
            for i in range(tri_count):
                t_offset = tri_start + i * 12
                uvs = []
                # DashViewer Order: b, a, c (offsets 2, 0, 4)
                # b
                uvs.append((self.data[t_offset + 2], self.data[t_offset + 3]))
                # a
                uvs.append((self.data[t_offset + 0], self.data[t_offset + 1]))
                # c
                uvs.append((self.data[t_offset + 4], self.data[t_offset + 5]))

                # DashViewer Order: bi, ai, ci (offsets 9, 8, 10)
                indices = (
                    self.data[t_offset + 9],
                    self.data[t_offset + 8],
                    self.data[t_offset + 10],
                )
                triangles.append({"indices": indices, "uvs": uvs})

        # Parse quads
        quads = []
        if quad_start and quad_count > 0:
            for i in range(quad_count):
                q_offset = quad_start + i * 12
                uvs = []
                # DashViewer Order: b, a, c, d (offsets 2, 0, 4, 6)
                # b
                uvs.append((self.data[q_offset + 2], self.data[q_offset + 3]))
                # a
                uvs.append((self.data[q_offset + 0], self.data[q_offset + 1]))
                # c
                uvs.append((self.data[q_offset + 4], self.data[q_offset + 5]))
                # d
                uvs.append((self.data[q_offset + 6], self.data[q_offset + 7]))

                # DashViewer Order: bi, ai, ci, di (offsets 9, 8, 10, 11)
                indices = (
                    self.data[q_offset + 9],
                    self.data[q_offset + 8],
                    self.data[q_offset + 10],
                    self.data[q_offset + 11],
                )
                quads.append({"indices": indices, "uvs": uvs})

        return {
            "number": limb_number,
            "vertices": vertices,
            "triangles": triangles,
            "quads": quads,
            "texture_page": texture_page,
            "clut_page": clut_page,
        }

    def parse_animations(self, hierarchy_start, limb_count):
        """Parse animation data from the hierarchy section.
        
        Based on DashViewer's api_readAnims (JavaScript):
        - Animation pointer table starts at hierarchy_start + 4
        - Table ends at the address stored at hierarchy_start (limb_trans_ofs)
        - Each animation pointer points to a frame pointer table
        - Each frame is packed 12-bit values:
          - 4 bytes: Root position (packed 12-bit X, Y, Z)
          - 4.5 bytes per bone: Rotation (alternating 5/4 bytes for even/odd)
        """
        animations = []
        
        if hierarchy_start is None or (hierarchy_start >> 24) != 0:
            return animations
        
        # firstOfs = value at hierarchy_start (points to limb translations)
        # This tells us where the animation pointer table ends
        first_ptr_addr = self.read_int(hierarchy_start)
        first_ptr_ofs = self.ps1_to_file_offset(first_ptr_addr)
        
        if first_ptr_ofs is None or (first_ptr_ofs >> 24) != 0:
            return animations
        
        # Animation pointer table starts at hierarchy_start + 4
        anim_table_start = hierarchy_start + 4
        
        # Read animation pointers from anim_table_start to first_ptr_ofs
        anim_pointers = []
        for ofs in range(anim_table_start, first_ptr_ofs, 4):
            if ofs + 4 > len(self.data):
                break
            ptr_addr = self.read_int(ofs)
            if ptr_addr == 0:
                continue
            ptr_ofs = self.ps1_to_file_offset(ptr_addr)
            if ptr_ofs is not None and (ptr_ofs >> 24) == 0:
                anim_pointers.append(ptr_ofs)
        
        # Parse each animation
        for anim_idx, anim_ptr in enumerate(anim_pointers):
            # Each animation has its own frame pointer table
            # First pointer tells us where frame data starts (and where table ends)
            first_frame_addr = self.read_int(anim_ptr)
            first_frame_ofs = self.ps1_to_file_offset(first_frame_addr)
            
            if first_frame_ofs is None or (first_frame_ofs >> 24) != 0:
                continue
            
            # Read frame pointers for this animation
            frame_ptrs = []
            for ofs in range(anim_ptr, first_frame_ofs, 4):
                if ofs + 4 > len(self.data):
                    break
                p_addr = self.read_int(ofs)
                p_ofs = self.ps1_to_file_offset(p_addr)
                if p_ofs is not None and (p_ofs >> 24) == 0:
                    frame_ptrs.append(p_ofs)
            
            if len(frame_ptrs) < 2:
                continue
            
            # Calculate bone count from frame size
            # Frame size = 4 bytes position + 4.5 bytes per bone (average)
            frame_len = frame_ptrs[1] - frame_ptrs[0]
            bone_count = int((frame_len - 4.5) / 4.5)
            
            if bone_count <= 0:
                bone_count = limb_count
            
            frames = []
            
            for frame_idx, frame_ofs in enumerate(frame_ptrs):
                if frame_ofs + 8 > len(self.data):
                    break
                
                ofs = frame_ofs
                
                # Read root position (4 bytes, packed 12-bit values)
                raw_x = self.read_ushort(ofs + 0) & 0xFFF
                raw_y = self.read_ushort(ofs + 1) >> 4
                raw_z = self.read_ushort(ofs + 3) & 0xFFF
                
                # Sign extension for 12-bit values
                def sign_extend_12(val):
                    if val & 0x800:
                        return -((0x800 - (val & 0x7FF)))
                    return val
                
                pos_x = sign_extend_12(raw_x)
                pos_y = sign_extend_12(raw_y)
                pos_z = sign_extend_12(raw_z)
                
                ofs += 4
                
                # Read per-bone rotations (alternating 5/4 bytes)
                bone_rotations = []
                for bone_idx in range(bone_count):
                    if ofs + 5 > len(self.data):
                        break
                    
                    if (bone_idx % 2) == 0:
                        # Even bones: 5 bytes
                        rx = (self.read_ushort(ofs + 0) >> 4) & 0xFFF
                        ry = self.read_ushort(ofs + 2) & 0xFFF
                        rz = (self.read_ushort(ofs + 3) >> 4) & 0xFFF
                        ofs += 5
                    else:
                        # Odd bones: 4 bytes
                        rx = self.read_ushort(ofs + 0) & 0xFFF
                        ry = (self.read_ushort(ofs + 1) >> 4) & 0xFFF
                        rz = self.read_ushort(ofs + 3) & 0xFFF
                        ofs += 4
                    
                    # Convert to degrees: val / 0xFFF * 360
                    rot_x = (rx / 0xFFF) * 360.0
                    rot_y = (ry / 0xFFF) * 360.0
                    rot_z = (rz / 0xFFF) * 360.0
                    
                    bone_rotations.append((rot_x, rot_y, rot_z))
                
                frame = {
                    "root_translation": (pos_x, pos_y, pos_z),
                    "bone_rotations": bone_rotations,
                }
                frames.append(frame)
            
            if frames:
                animations.append({
                    "index": anim_idx,
                    "frame_count": len(frames),
                    "bone_count": bone_count,
                    "frames": frames
                })
        
        return animations
