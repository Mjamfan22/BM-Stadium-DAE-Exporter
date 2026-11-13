# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded optional editor metadata; rendering stays in standard normals and UVs."""
import base64
import numpy as np
import zstandard

MAX_METADATA = 64 * 1024 * 1024
ATTRIBUTES = ('crease_edge', 'bevel_weight_edge', 'freestyle_edge', '.freestyle_edge')


def capture(mesh, vertex_ids, smooth, line_ids=None):
    n = len(mesh.edges)
    edges = np.empty(n * 2, dtype=np.uint32)
    mesh.edges.foreach_get('vertices', edges)
    sharp, seam = np.empty(n, dtype=np.bool_), np.empty(n, dtype=np.bool_)
    mesh.edges.foreach_get('use_edge_sharp', sharp)
    mesh.edges.foreach_get('use_seam', seam)
    values = {'sharp': sharp, 'seam': seam}
    types = {}
    for name in ATTRIBUTES:
        attr = mesh.attributes.get(name)
        if attr and attr.domain == 'EDGE' and attr.data_type in {'FLOAT', 'BOOLEAN', 'INT'}:
            a = np.empty(n, dtype=np.float32)
            attr.data.foreach_get('value', a)
            if not np.isfinite(a).all():
                raise ValueError(f'Non-finite edge attribute {name}')
            values[name] = a
            types[name] = attr.data_type
    marked = np.logical_or.reduce([a != 0 for a in values.values()])
    smooth = np.asarray(smooth, dtype=np.uint8)
    if not marked.any() and (not len(smooth) or smooth.all()):
        return None
    result = {'version': 1, 'vertex_ids': np.asarray(vertex_ids, dtype='<u4').tobytes(),
              'edges': edges.reshape(-1, 2)[marked].astype('<u4').tobytes(), 'smooth': smooth.tobytes(),
              'attributes': {name: np.asarray(a[marked], dtype='<f4').tobytes() for name, a in values.items()},
              'attribute_types': types}
    if line_ids is not None:
        result['line_ids'] = np.asarray(line_ids, dtype='<u4').tobytes()
    return result


def encode(metadata):
    from .cache_io import pack
    raw = pack(metadata)
    if len(raw) > MAX_METADATA:
        raise ValueError('Edge-mark metadata exceeds 64 MiB; disable Preserve Edge Marks for this export')
    return zstandard.ZstdCompressor(level=3).compress(raw)


def decode(payload):
    from .cache_io import Unpacker
    if not isinstance(payload, bytes) or len(payload) > MAX_METADATA:
        raise ValueError('Invalid edge-mark metadata payload')
    raw = zstandard.ZstdDecompressor(max_window_size=64 * 1024).decompress(payload, max_output_size=MAX_METADATA, allow_extra_data=False)
    u = Unpacker(raw); value = u.read()
    if u.pos != len(raw) or not isinstance(value, dict) or value.get('version') != 1:
        raise ValueError('Unsupported edge-mark metadata')
    ids, edges, smooth = value.get('vertex_ids'), value.get('edges'), value.get('smooth')
    if not all(isinstance(a, bytes) for a in (ids, edges, smooth)) or len(ids) % 4 or len(edges) % 8 or len(smooth) * 12 != len(ids):
        raise ValueError('Invalid edge-mark topology buffers')
    attrs = value.get('attributes')
    if not isinstance(attrs, dict) or any(k not in {'sharp', 'seam', *ATTRIBUTES} for k in attrs):
        raise ValueError('Invalid edge-mark attribute names')
    for a in attrs.values():
        if not isinstance(a, bytes) or len(a) * 2 != len(edges) or not np.isfinite(np.frombuffer(a, dtype='<f4')).all():
            raise ValueError('Invalid edge-mark attribute buffer')
    types = value.get('attribute_types', {})
    if not isinstance(types, dict) or any(k not in ATTRIBUTES or v not in {'FLOAT', 'BOOLEAN', 'INT'} for k, v in types.items()):
        raise ValueError('Invalid edge-mark attribute types')
    line_ids = value.get('line_ids', b'')
    if not isinstance(line_ids, bytes) or len(line_ids) % 4:
        raise ValueError('Invalid edge-mark line buffer')
    if len(ids) and np.frombuffer(ids, dtype='<u4').max() > 5_000_000:
        raise ValueError('Invalid edge-mark vertex identity')
    return value


def xml_encode(metadata):
    return base64.b64encode(encode(metadata)).decode('ascii')


def xml_decode(text):
    if len(text) > MAX_METADATA * 2:
        raise ValueError('Edge-mark XML payload is too large')
    return decode(base64.b64decode(text, validate=True))


def topology(metadata, vertices, corner_indices, line_vertices=None, line_indices=None):
    """Join vertices only by explicit source identity, never by proximity."""
    ids = np.frombuffer(metadata['vertex_ids'], dtype='<u4')
    if len(ids) != len(vertices):
        raise ValueError('Edge-mark metadata does not match the geometry vertex count')
    unique, first, inverse = np.unique(ids, return_index=True, return_inverse=True)
    positions = np.asarray(vertices)[first]
    if not np.array_equal(np.asarray(vertices), positions[inverse]):
        raise ValueError('Edge-mark source identities have inconsistent positions')
    dense_ids = unique.tolist()
    faces = inverse[corner_indices]
    loose = None
    if line_indices is not None:
        lids = np.frombuffer(metadata.get('line_ids', b''), dtype='<u4')
        if line_vertices is None or len(lids) != len(line_vertices):
            raise ValueError('Edge-mark metadata does not match the loose-edge vertices')
        lookup = {int(vi): i for i, vi in enumerate(dense_ids)}
        additions, remap = [], []
        for source_id, co in zip(lids, line_vertices):
            vi = int(source_id)
            if vi not in lookup:
                lookup[vi] = len(dense_ids); dense_ids.append(vi); additions.append(co)
            remap.append(lookup[vi])
        if additions:
            positions = np.concatenate((positions, np.asarray(additions)))
        loose = np.asarray(remap)[np.asarray(line_indices, dtype=np.int64)]
    return positions, faces, dense_ids, loose


def restore(mesh, metadata, dense_ids):
    pairs = np.frombuffer(metadata['edges'], dtype='<u4').reshape(-1, 2)
    original = {int(v): i for i, v in enumerate(dense_ids)}
    edge_vertices = np.empty(len(mesh.edges) * 2, dtype=np.int32)
    mesh.edges.foreach_get('vertices', edge_vertices)
    lookup = {tuple(sorted(e)): i for i, e in enumerate(edge_vertices.reshape(-1, 2))}
    target = []
    for a, b in pairs:
        key = tuple(sorted((original.get(int(a), -1), original.get(int(b), -1))))
        target.append(lookup.get(key, -1))
    target = np.asarray(target, dtype=np.int64)
    valid = target >= 0
    for name, buffer in metadata['attributes'].items():
        values = np.frombuffer(buffer, dtype='<f4')
        out = np.zeros(len(mesh.edges), dtype=np.float32)
        out[target[valid]] = values[valid]
        if name in {'sharp', 'seam'}:
            mesh.edges.foreach_set('use_edge_sharp' if name == 'sharp' else 'use_seam', out.astype(np.bool_))
        else:
            typ = metadata.get('attribute_types', {}).get(name, 'FLOAT')
            attr = mesh.attributes.get(name) or mesh.attributes.new(name, typ, 'EDGE')
            attr.data.foreach_set('value', out.astype(np.bool_ if typ == 'BOOLEAN' else np.int32 if typ == 'INT' else np.float32))
    mesh.update()


def infer(mesh, corner_normals=None):
    """Infer shading/UV discontinuities at exact edge positions without welding."""
    if not len(mesh.polygons):
        return 0
    positions = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.vertices.foreach_get('co', positions); positions = positions.reshape(-1, 3)
    loop_vertices = np.empty(len(mesh.loops), dtype=np.int32); mesh.loops.foreach_get('vertex_index', loop_vertices)
    edge_indices = np.empty(len(mesh.loops), dtype=np.int32); mesh.loops.foreach_get('edge_index', edge_indices)
    uv = []
    for layer in mesh.uv_layers:
        values = np.empty(len(mesh.loops) * 2, dtype=np.float32); layer.data.foreach_get('uv', values)
        uv.append(values.reshape(-1, 2))
    if not uv and corner_normals is None:
        return 0
    starts = np.empty(len(mesh.polygons), dtype=np.int32)
    sizes = np.empty(len(mesh.polygons), dtype=np.int32)
    mesh.polygons.foreach_get('loop_start', starts); mesh.polygons.foreach_get('loop_total', sizes)
    next_loop = np.arange(len(mesh.loops), dtype=np.int32) + 1
    next_loop[starts + sizes - 1] = starts
    position_keys = [tuple(p) for p in positions]
    groups = {}
    for first, second in enumerate(next_loop):
        pa, pb = position_keys[loop_vertices[first]], position_keys[loop_vertices[second]]
        if pa == pb:
            continue
        a, b = (first, int(second)) if pa < pb else (int(second), first)
        groups.setdefault((pa, pb) if pa < pb else (pb, pa), []).append((int(edge_indices[first]), a, b))
    pairs = np.asarray([pair for pair in groups.values() if len(pair) == 2], dtype=np.int32).reshape(-1, 2, 3)
    sharp, seam = np.zeros(len(mesh.edges), dtype=np.bool_), np.zeros(len(mesh.edges), dtype=np.bool_)
    if len(pairs):
        left, right = pairs[:, 0], pairs[:, 1]
        hard = np.zeros(len(pairs), dtype=bool)
        if corner_normals is not None:
            hard = np.any(abs(corner_normals[left[:, 1:]] - corner_normals[right[:, 1:]]) > 1e-5, axis=(1, 2))
        split = np.zeros(len(pairs), dtype=bool)
        for layer in uv:
            split |= np.any(abs(layer[left[:, 1:]] - layer[right[:, 1:]]) > 1e-6, axis=(1, 2))
        sharp[pairs[hard, :, 0].reshape(-1)] = True
        seam[pairs[split, :, 0].reshape(-1)] = True
    mesh.edges.foreach_set('use_edge_sharp', sharp); mesh.edges.foreach_set('use_seam', seam)
    return int(np.count_nonzero(sharp | seam))
