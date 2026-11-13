# SPDX-License-Identifier: GPL-3.0-or-later
"""BeamNG cache v26/v31 IO. v31 follows BeamNG's published format, not XML.

Legacy decoding uses the attributed Dummiesman decoder in legacy_cache.
All runtime dependencies ship with this add-on or the tested Blender build.
"""
import io
import math
from pathlib import Path
import struct

import numpy as np
import zstandard

LIMIT = 512 * 1024 * 1024
MAX_ITEMS = 5_000_000
VECTOR_SIZES = [20, 24, 4, 4, 4, 4, 8, 12, 8, 12, 4, 12, 12, 8, 12, 8, 12, 8, 52]


class Unpacker:
    def __init__(self, data):
        self.data = memoryview(data)
        self.pos = 0

    def take(self, n):
        if n < 0 or n > len(self.data) - self.pos:
            raise ValueError('Truncated MessagePack data')
        p = self.pos
        self.pos += n
        return self.data[p:self.pos].tobytes()

    def number(self, fmt):
        return struct.unpack(fmt, self.take(struct.calcsize(fmt)))[0]

    def read(self, depth=0):
        if depth > 64:
            raise ValueError('MessagePack nesting limit exceeded')
        c = self.number('B')
        if c < 0x80:
            return c
        if c >= 0xe0:
            return c - 256
        if c == 0xc0:
            return None
        if c in (0xc2, 0xc3):
            return c == 0xc3
        fmts = {0xca: '>f', 0xcb: '>d', 0xcc: '>B', 0xcd: '>H', 0xce: '>I', 0xcf: '>Q',
                0xd0: '>b', 0xd1: '>h', 0xd2: '>i', 0xd3: '>q'}
        if c in fmts:
            v = self.number(fmts[c])
            if isinstance(v, float) and not math.isfinite(v):
                raise ValueError('Non-finite cache number')
            return v
        if 0xa0 <= c <= 0xbf or c in (0xd9, 0xda, 0xdb, 0xc4, 0xc5, 0xc6):
            n = c & 31 if 0xa0 <= c <= 0xbf else self.number({0xd9: '>B', 0xda: '>H', 0xdb: '>I', 0xc4: '>B', 0xc5: '>H', 0xc6: '>I'}[c])
            b = self.take(n)
            return b if c in (0xc4, 0xc5, 0xc6) else b.decode('utf-8')
        is_map = 0x80 <= c <= 0x8f or c in (0xde, 0xdf)
        is_array = 0x90 <= c <= 0x9f or c in (0xdc, 0xdd)
        if is_map or is_array:
            n = c & 15 if c < 0xa0 else self.number('>H' if c in (0xdc, 0xde) else '>I')
            if n > MAX_ITEMS or n > len(self.data) - self.pos:
                raise ValueError('Invalid cache container size')
            if is_map:
                result = {}
                for _ in range(n):
                    k = self.read(depth + 1)
                    result[k] = self.read(depth + 1)
                return result
            return [self.read(depth + 1) for _ in range(n)]
        raise ValueError(f'Unsupported MessagePack marker 0x{c:02x}')


def pack(v):
    if v is None:
        return b'\xc0'
    if isinstance(v, bool):
        return b'\xc3' if v else b'\xc2'
    if isinstance(v, (int, np.integer)):
        return b'\xd3' + struct.pack('>q', int(v))
    if isinstance(v, (float, np.floating)):
        if not math.isfinite(v):
            raise ValueError('Non-finite export number')
        return b'\xca' + struct.pack('>f', float(v))
    if isinstance(v, str):
        b = v.encode('utf-8')
        return b'\xdb' + struct.pack('>I', len(b)) + b
    if isinstance(v, bytes):
        return b'\xc6' + struct.pack('>I', len(v)) + v
    if isinstance(v, dict):
        return b'\xdf' + struct.pack('>I', len(v)) + b''.join(pack(k) + pack(a) for k, a in v.items())
    return b'\xdd' + struct.pack('>I', len(v)) + b''.join(pack(a) for a in v)


def count(value):
    if type(value) is not int or not 0 <= value <= MAX_ITEMS:
        raise ValueError('Invalid cache item count')
    return value


def vector(u, expected=None):
    n, size, b = count(u.read()), count(u.read()), u.read()
    if n == 0 and b in (None, [], {}):
        b = b''
    if not isinstance(b, bytes) or len(b) != n * size or (n and expected is not None and size != expected):
        raise ValueError(f'Invalid cache vector: {n} elements of {size} bytes')
    return n, size, b


def array(v, dtype, width=1):
    result = np.frombuffer(v[2], dtype=dtype).copy().reshape(-1, width)
    if np.issubdtype(result.dtype, np.floating) and not np.isfinite(result).all():
        raise ValueError('Non-finite cache geometry')
    return result if width > 1 else result.reshape(-1)


def floats(v, width):
    if isinstance(v, bytes):
        v = struct.unpack('<' + 'f' * width, v)
    if len(v) != width or not all(math.isfinite(float(a)) for a in v):
        raise ValueError('Invalid cache vector value')
    return list(v)


def read_v31(raw):
    version, hsize = struct.unpack('<II', raw[:8])
    if not 0 < hsize <= len(raw) - 8:
        raise ValueError('Invalid cache header size')
    hu = Unpacker(raw[8:8 + hsize])
    header = hu.read()
    if hu.pos != hsize or not isinstance(header, dict):
        raise ValueError('Invalid cache header')
    body = raw[8 + hsize:]
    if header.get('bodysize', len(body)) != len(body):
        raise ValueError('Cache body size does not match its header')
    if header.get('compression'):
        body = zstandard.ZstdDecompressor(max_window_size=128 * 1024).decompress(
            body, max_output_size=LIMIT, allow_extra_data=False)
    if len(body) > LIMIT:
        raise ValueError('Cache body exceeds 512 MiB')
    u = Unpacker(body)
    info = [u.read() for _ in range(6)]
    vec = [vector(u, size) for size in VECTOR_SIZES]
    names = [u.read() for _ in range(count(u.read()))]
    if not all(isinstance(n, str) for n in names):
        raise ValueError('Invalid cache names')
    meshes = []
    for _ in range(count(u.read())):
        typ = u.read()
        if typ == 4:
            meshes.append({'is_null': True, 'mesh_type': typ})
            continue
        if typ not in (0, 1):
            raise ValueError(f'Unsupported cache mesh type {typ}; standard and skin reference meshes are supported')
        frames, matframes, parent = u.read(), u.read(), u.read()
        bounds, center, radius = floats(u.read(), 6), floats(u.read(), 3), u.read()
        blocks = [vector(u, s) for s in (12, 8, 8, 4, 12, 1, 12, 4, 16)]
        vpf, flags = u.read(), u.read()
        m = {'is_dae': False, 'mesh_type': typ, 'is_null': False, 'num_frames': frames,
             'verts_per_frame': vpf, 'mesh_flags': flags, 'cache_parent_mesh': parent,
             'vertices': array(blocks[0], '<f4', 3), 'uv0': array(blocks[1], '<f4', 2),
             'uv1': array(blocks[2], '<f4', 2), 'colors': array(blocks[3], 'u1', 4),
             'normals': array(blocks[4], '<f4', 3), 'indices': array(blocks[7], '<u4'),
             'primitives': array(blocks[6], '<u4', 3)}
        if not m['normals'].size and blocks[5][0]:
            from .normal_table import NORMAL_TABLE
            m['normals'] = NORMAL_TABLE[array(blocks[5], 'u1')].copy()
        if parent >= 0:
            if parent >= len(meshes):
                raise ValueError('Invalid parent mesh reference')
            for key in ('vertices', 'uv0', 'uv1', 'colors', 'normals'):
                if not m[key].size:
                    m[key] = meshes[parent].get(key)
        if typ == 1:
            if parent < 0:
                vector(u, 12); vector(u, 12)
            vector(u, 64)
            if parent < 0:
                for s in (4, 4, 4, 4):
                    vector(u, s)
        for key in ('uv0', 'uv1', 'colors', 'normals'):
            if m[key] is not None and not m[key].size:
                m.pop(key)
        meshes.append(m)
    sequences = []
    for _ in range(count(u.read())):
        fields = [u.read() for _ in range(15)]
        sets = [u.read() for _ in range(6)]
        sequences.append({'name': names[fields[0]] if 0 <= fields[0] < len(names) else '',
                          'flags': fields[1], 'keyframes': fields[2], 'duration': fields[3]})
    materials = []
    if u.pos < len(body):
        n = count(u.read())
        has_pbr = u.pos < len(body) and body[u.pos] in (0xc2, 0xc3)
        has_pbr = bool(u.read()) if has_pbr else False
        for _ in range(n):
            name, flags, reflect, bump, detail, ds, ra = [u.read() for _ in range(7)]
            mat = {'name': name, 'flags': flags}
            if has_pbr:
                mat.update(base_color=u.read(), roughness=u.read(), metallic=u.read())
            materials.append(mat)
    if u.pos != len(body):
        raise ValueError('Unexpected trailing cache body data')
    editor_meshes = header.get('blender_mesh_metadata')
    if editor_meshes is not None:
        from .edge_marks import decode
        if not isinstance(editor_meshes, list) or len(editor_meshes) != len(meshes):
            raise ValueError('Invalid cache editor metadata table')
        for mesh, payload in zip(meshes, editor_meshes):
            if payload is not None:
                mesh['editor_mesh'] = decode(payload)
    nodes = []
    rots = array(vec[6], '<i2', 4) / 32767.0
    trans = array(vec[7], '<f4', 3)
    for i, (ni, parent, first, child, sibling) in enumerate(struct.iter_unpack('<5i', vec[0][2])):
        if i >= len(rots) or i >= len(trans):
            raise ValueError('Missing node transform')
        q = rots[i].tolist(); q[3] = -q[3]
        nodes.append({'name': names[ni], 'parent_index': parent, 'first_object': first,
                      'first_child': child, 'next_sibling': sibling, 'quaternion': q,
                      'translation': trans[i].tolist(), 'scale': [1, 1, 1]})
    objects = [dict(zip(('name_index', 'num_meshes', 'start_mesh', 'node_index', 'next_sibling', 'first_decal'), row))
               for row in struct.iter_unpack('<6i', vec[1][2])]
    for oi, obj in enumerate(objects):
        obj['subshape'] = next((j for j, (start, length) in enumerate(zip(array(vec[3], '<i4'), array(vec[5], '<i4')))
                                if start <= oi < start + length), 0)
    details = []
    for row in struct.iter_unpack('<3i3fi2i2IfI', vec[18][2]):
        details.append(dict(zip(('name', 'subshape', 'mesh_slot', 'size', 'average_error', 'max_error', 'poly_count',
                                 'billboard_dimension', 'billboard_detail_level', 'billboard_equator_steps',
                                 'billboard_polar_steps', 'billboard_polar_angle', 'billboard_include_poles'),
                                [names[row[0]], *row[1:]])))
    return {'meshes': meshes, 'nodes': nodes, 'objects': objects, 'names': names, 'materials': materials,
            'unit_meter': 1.0, 'cache_metadata': {'version': 31, 'exporter_version': version >> 16,
            'details': details, 'sequences': sequences, 'source_header': {k: v for k, v in header.items() if isinstance(v, (str, bool, int, float))}}}


def read_legacy(raw):
    from ..legacy_cache.tsshape import TSShape
    from ..legacy_cache.tsmesh import TSNullMesh, TSSkinnedMesh
    size, start16, start8 = struct.unpack('<3i', raw[4:16])
    if not 0 <= start16 <= start8 <= size or size * 4 > len(raw) - 16:
        raise ValueError('Invalid legacy cache buffer sizes')
    shape = TSShape()
    shape.read(io.BytesIO(raw))
    nodes, meshes = [], []
    for n in shape.nodes:
        q = n.rotation.to_quat_f()
        nodes.append({'name': shape.names[n.name_index], 'parent_index': n.parent_index,
                      'quaternion': [q.x, q.y, q.z, -q.w], 'translation': n.translation, 'scale': [1, 1, 1]})
    for m in shape.meshes:
        if isinstance(m, TSNullMesh):
            meshes.append({'is_null': True, 'mesh_type': 4})
            continue
        d = {'is_null': False, 'is_dae': False, 'mesh_type': int(isinstance(m, TSSkinnedMesh)),
             'vertices': np.array(m.vertices, dtype=np.float32),
             'normals': np.array(m.normals, dtype=np.float32),
             'indices': np.array(m.indices, dtype=np.int64),
             'primitives': np.array([[p.start, p.num_elements, p.material_index | p.type | (1 << 29) | ((1 << 28) if p.has_no_material else 0)] for p in m.primitives], dtype=np.uint32)}
        for key, val, dtype in [('uv0', m.tvertices, np.float32), ('uv1', m.t2vertices, np.float32), ('colors', m.colors, np.float32)]:
            if val:
                d[key] = np.array(val, dtype=dtype)
                if key == 'colors':
                    d[key] = np.rint(d[key] * 255).astype(np.uint8)
        meshes.append(d)
    objects = [{'name_index': o.name_index, 'num_meshes': o.num_meshes, 'start_mesh': o.start_mesh_index,
                'node_index': o.node_index, 'subshape': shape.get_sub_shape_for_object(i)} for i, o in enumerate(shape.objects)]
    details = [{'name': shape.names[d.name_index], 'subshape': d.sub_shape_num,
                'mesh_slot': d.object_detail_num, 'size': d.size} for d in shape.details]
    return {'meshes': meshes, 'nodes': nodes, 'objects': objects, 'names': shape.names,
            'materials': [{'name': m.name, 'flags': m.flags} for m in shape.materials], 'unit_meter': 1.0,
            'cache_metadata': {'version': raw[0], 'details': details,
                               'sequence_count': len(shape.sequences)}}


def read_cache(path):
    p = Path(path)
    if p.stat().st_size > LIMIT:
        raise ValueError('Cache file exceeds 512 MiB')
    raw = p.read_bytes()
    if len(raw) < 16:
        raise ValueError('Truncated cache file')
    ver = struct.unpack_from('<I', raw)[0] & 0xffff
    if ver == 31:
        return read_v31(raw)
    if ver == 26:
        return read_legacy(raw)
    raise ValueError(f'Unsupported CDAE version {ver}; supported versions: 26 and 31')


def _block(values, dtype, width):
    source = np.asarray(values)
    if np.issubdtype(source.dtype, np.floating) and not np.isfinite(source).all():
        raise ValueError('Non-finite cache export attribute')
    if dtype == 'u1' and width == 4 and source.dtype != np.uint8:
        source = np.clip(np.rint(source * 255.0), 0, 255)
    a = np.asarray(source, dtype=dtype).reshape(-1, width)
    return [len(a), np.dtype(dtype).itemsize * width, a.tobytes()]


def write_cache(path, data, compress=True):
    """Write standard v31 static meshes with real bounds and a usable detail.

    Linear world transforms are baked by the export operator; translations and
    exact BeamNG object/material names remain explicit in the file.
    """
    meshes, nodes, objects, names = data['meshes'], data['nodes'], data['objects'], list(data['names'])
    all_world = []
    for o in objects:
        for slot in range(o['num_meshes']):
            m = meshes[o['start_mesh'] + slot]
            if not m.get('is_null'):
                all_world.append(np.asarray(m['vertices']) + np.asarray(nodes[o['node_index']]['translation']))
    pts = np.concatenate(all_world) if all_world else np.zeros((1, 3))
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    center = (lo + hi) / 2
    radius = float(np.linalg.norm(pts - center, axis=1).max())
    details = data.get('details') or [{'name': 'detail2', 'subshape': 0, 'mesh_slot': 0, 'size': 2.}]
    raw_nodes = [[i, -1, i, -1, -1] for i in range(len(nodes))]
    raw_objects = [[o['name_index'], o['num_meshes'], o['start_mesh'], o['node_index'], -1, -1] for o in objects]
    subshapes = sorted(set(o.get('subshape', 0) for o in objects))
    if subshapes != list(range(len(subshapes))):
        raise ValueError('Invalid export subshape layout')
    first = [next(i for i, o in enumerate(objects) if o.get('subshape', 0) == j) for j in subshapes]
    counts = [sum(o.get('subshape', 0) == j for o in objects) for j in subshapes]
    v = [
        _block(raw_nodes, '<i4', 5), _block(raw_objects, '<i4', 6),
        _block(first, '<i4', 1), _block(first, '<i4', 1),
        _block(counts, '<i4', 1), _block(counts, '<i4', 1),
        _block([[0, 0, 0, -32767]] * len(nodes), '<i2', 4),
        _block([n['translation'] for n in nodes], '<f4', 3),
    ]
    v += [[0, s, b''] for s in VECTOR_SIZES[8:16]]
    states = b''.join(struct.pack('<fii', 1, 0, 0) for _ in objects)
    detail_bytes = []
    for d in details:
        ni = len(names); names.append(d['name'])
        slot, subshape = int(d['mesh_slot']), int(d['subshape'])
        triangles = sum(len(meshes[o['start_mesh'] + slot].get('indices', [])) // 3 for o in objects
                        if o.get('subshape', 0) == subshape and 0 <= slot < o['num_meshes'])
        detail_bytes.append(struct.pack('<3i3fi2i2IfI', ni, subshape, slot, float(d['size']),
                            float(d.get('average_error', -1)), float(d.get('max_error', -1)), triangles,
                            *[int(d.get(k, 0)) for k in ('billboard_dimension', 'billboard_detail_level', 'billboard_equator_steps', 'billboard_polar_steps')],
                            float(d.get('billboard_polar_angle', 0)), int(d.get('billboard_include_poles', 0))))
    v += [[len(objects), 12, states], [0, 8, b''], [len(details), 52, b''.join(detail_bytes)]]
    visible = [(i, d) for i, d in enumerate(details) if d['size'] >= 0]
    smallest = min(visible, key=lambda pair: pair[1]['size']) if visible else (0, {'size': 0.})
    values = [float(smallest[1]['size']), smallest[0], radius, radius, center.tolist(), np.concatenate((lo, hi)).tolist()]
    for b in v:
        values.extend(b)
    values += [len(names)] + names + [len(meshes)]
    for m in meshes:
        if m.get('is_null'):
            values.append(4)
            continue
        a = np.asarray(m['vertices'], dtype=np.float32)
        if m.get('normals') is None:
            idx = np.asarray(m['indices']).reshape(-1, 3)
            t = a[idx]
            normals = -np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
            lengths = np.linalg.norm(normals, axis=1, keepdims=True)
            normals = np.divide(normals, lengths, out=np.zeros_like(normals), where=lengths > 1e-20)
            m['normals'] = np.repeat(normals, 3, axis=0)
        m['primitives'] = np.array(m['primitives'], dtype=np.uint32, copy=True)
        m['primitives'][:, 2] |= 1 << 29
        mn, mx = a.min(axis=0), a.max(axis=0)
        c = (mn + mx) / 2
        values += [0, 1, 1, -1, np.concatenate((mn, mx)).tolist(), c.tolist(), float(np.linalg.norm(a - c, axis=1).max())]
        for key, dtype, w in [('vertices', '<f4', 3), ('uv0', '<f4', 2), ('uv1', '<f4', 2),
                               ('colors', 'u1', 4), ('normals', '<f4', 3), ('encoded_normals', 'u1', 1),
                               ('primitives', '<u4', 3), ('indices', '<u4', 1), ('tangents', '<f4', 4)]:
            values.extend(_block(m.get(key, []), dtype, w))
        values += [len(a), int(m.get('mesh_flags', 0))]
    values += [0, len(data['materials'])]
    for m in data['materials']:
        values += [m['name'], int(m.get('flags', 3)), 0, 0, 0, 1., 0.]
    body = b''.join(pack(x) for x in values)
    encoded = zstandard.ZstdCompressor(level=3).compress(body) if compress else body
    header_values = {'compression': compress, 'bodysize': len(encoded), 'objectNames': [names[o['name_index']] for o in objects], 'info': 'BeamNG Collada Importer/Exporter 1.3.0'}
    if any(m.get('editor_mesh') is not None for m in meshes):
        from .edge_marks import encode
        header_values['blender_mesh_metadata'] = [encode(m['editor_mesh']) if m.get('editor_mesh') is not None else None for m in meshes]
    header = pack(header_values)
    if len(header) + len(encoded) + 8 > LIMIT:
        raise ValueError('Exported cache exceeds the supported 512 MiB limit')
    Path(path).write_bytes(struct.pack('<II', 31, len(header)) + header + encoded)
