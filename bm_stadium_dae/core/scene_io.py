# SPDX-License-Identifier: GPL-3.0-or-later
"""Scene/coordinate handling around Blenux's native COLLADA geometry codec."""
import copy
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import bpy
from mathutils import Matrix, Vector
import numpy as np

from .cache_io import read_cache
from .edge_marks import xml_encode as encode_editor_mesh, xml_decode as decode_editor_mesh

NS = 'http://www.collada.org/2005/11/COLLADASchema'
ET.register_namespace('', NS)


def tag(name):
    return '{' + NS + '}' + name


def source_name(item, kind='object'):
    if item.name == item.get('beamng_display_name', ''):
        return item.get('beamng_source_name', item.name)
    return item.name


def scene_unit_scale(context):
    """Meters per Blender unit, without changing the user's scene settings."""
    value = float(context.scene.unit_settings.scale_length)
    if not math.isfinite(value) or value <= 0:
        raise ValueError('Scene Unit Scale must be a positive finite number')
    return value


def _xml_channels(geo):
    """Validate primitive indices and retain float color/UV channels before native IO."""
    xm = geo.find(tag('mesh'))
    if xm is None:
        raise ValueError('Only COLLADA mesh geometries are supported')
    sources = {}
    labels = {}
    for src in xm.findall(tag('source')):
        acc = src.find('./' + tag('technique_common') + '/' + tag('accessor'))
        stride = int(acc.get('stride', 1)) if acc is not None else 1
        a = np.fromstring(src.findtext(tag('float_array'), ''), sep=' ', dtype=np.float32)
        n = int(acc.get('count', len(a) // stride)) if acc is not None else len(a) // stride
        sources[src.get('id')] = a[:n * stride].reshape(-1, stride)
        labels[src.get('id')] = src.get('name') or src.get('id', '')
    vertices = {v.get('id'): v.findall(tag('input')) for v in xm.findall(tag('vertices'))}
    groups, discovered = [], {'TEXCOORD': {}, 'COLOR': {}}
    for group in xm:
        kind = group.tag.rsplit('}', 1)[-1]
        if kind not in {'triangles', 'lines'}:
            continue
        inputs = group.findall(tag('input'))
        if not inputs:
            raise ValueError('COLLADA primitive has no inputs')
        offsets = [int(e.get('offset', 0)) for e in inputs]
        if min(offsets) < 0 or max(offsets) >= 64:
            raise ValueError('Invalid COLLADA input offset')
        stride = max(offsets) + 1
        flat = np.fromstring(group.findtext(tag('p'), ''), sep=' ', dtype=np.int64)
        expected = int(group.get('count', 0)) * (3 if kind == 'triangles' else 2)
        if expected < 0 or len(flat) != expected * stride:
            raise ValueError('COLLADA primitive count does not match its index data')
        indices = flat.reshape(-1, stride)
        channels = {}
        for inp, offset in zip(inputs, offsets):
            refs = vertices.get(inp.get('source', '').lstrip('#')) if inp.get('semantic') == 'VERTEX' else [inp]
            if not refs:
                raise ValueError('Missing COLLADA vertex source')
            for ref in refs:
                sid = ref.get('source', '').lstrip('#')
                a = sources.get(sid)
                ids = indices[:, offset]
                if a is None or (len(ids) and (ids.min() < 0 or ids.max() >= len(a))):
                    raise ValueError('COLLADA attribute index is out of bounds')
                semantic = ref.get('semantic')
                required = {'POSITION': 3, 'NORMAL': 3, 'TEXCOORD': 2, 'COLOR': 3}.get(semantic, 1)
                if a.shape[1] < required:
                    raise ValueError(f'COLLADA {semantic} source has too few components')
                if kind == 'triangles' and semantic in discovered:
                    si = int(ref.get('set', 0))
                    if si < 0 or si >= 64:
                        raise ValueError('Invalid COLLADA attribute set')
                    label = labels[sid]
                    marker = '-colors-' if semantic == 'COLOR' else '-map-'
                    if marker in label:
                        label = label.split(marker, 1)[1]
                    discovered[semantic].setdefault(si, label)
                    values = a[ids, :4 if semantic == 'COLOR' else 2]
                    if semantic == 'COLOR' and values.shape[1] == 3:
                        values = np.column_stack((values, np.ones(len(values), dtype=np.float32)))
                    channels[(semantic, si)] = values
        if kind == 'triangles':
            groups.append((expected, channels))
    result = {}
    for semantic, sets in discovered.items():
        if not sets:
            continue
        width = 4 if semantic == 'COLOR' else 2
        arrays = [np.concatenate([ch.get((semantic, si), np.full((n, width), 1. if semantic == 'COLOR' else 0., dtype=np.float32))
                                  for n, ch in groups]) for si in sorted(sets)]
        if semantic == 'COLOR':
            result.update(colors=arrays[0], color_layers=arrays,
                          color_layer_names=[sets[si] for si in sorted(sets)])
        else:
            result.update(uv0=arrays[0], tvert_names=[sets[si] for si in sorted(sets)])
            if len(arrays) > 1:
                result['uv1'] = arrays[1]
            if len(arrays) > 2:
                result['uv_extra'] = arrays[2:]
    return result


def _matrix(element):
    m = Matrix.Identity(4)
    for child in element:
        kind = child.tag.rsplit('}', 1)[-1]
        if kind not in {'matrix', 'translate', 'rotate', 'scale', 'lookat', 'skew'}:
            continue
        v = [float(a) for a in (child.text or '').split()]
        if not all(math.isfinite(a) for a in v):
            raise ValueError('Non-finite COLLADA transform')
        if kind == 'matrix' and len(v) == 16:
            part = Matrix(np.asarray(v).reshape(4, 4).tolist())
        elif kind == 'translate' and len(v) == 3:
            part = Matrix.Translation(Vector(v))
        elif kind == 'rotate' and len(v) == 4:
            part = Matrix.Rotation(math.radians(v[3]), 4, Vector(v[:3]))
        elif kind == 'scale' and len(v) == 3:
            part = Matrix.Diagonal((*v, 1))
        else:
            raise ValueError(f'Unsupported or invalid COLLADA {kind} transform')
        m = m @ part
    return m


def _prepare_meshes(root):
    """Normalize COLLADA polygons with Blender's tessellator, preserving corners."""
    from mathutils.geometry import tessellate_polygon
    for xmlmesh in root.findall('.//' + tag('geometry') + '/' + tag('mesh')):
        sources = {}
        for source in xmlmesh.findall(tag('source')):
            values = source.find(tag('float_array'))
            if values is None:
                continue
            a = np.fromstring(values.text or '', sep=' ', dtype=np.float32)
            if not np.isfinite(a).all():
                raise ValueError('Non-finite COLLADA source array')
            accessor = source.find('./' + tag('technique_common') + '/' + tag('accessor'))
            stride = int(accessor.get('stride', 1)) if accessor is not None else 1
            offset = int(accessor.get('offset', 0)) if accessor is not None else 0
            if stride < 1 or offset < 0 or stride > 1024:
                raise ValueError('Invalid COLLADA accessor stride/offset')
            n = int(accessor.get('count', 0)) if accessor is not None else len(a) // stride
            if n < 0 or offset + n * stride > len(a):
                raise ValueError('COLLADA accessor exceeds source array')
            sources[source.get('id')] = a[offset:offset + n * stride].reshape(-1, stride)
            if offset:
                # The native geometry reader supports stride but not accessor offset.
                trimmed = a[offset:offset + n * stride]
                values.text = ' '.join(format(float(v), '.9g') for v in trimmed)
                values.set('count', str(len(trimmed)))
                accessor.set('offset', '0')
        vertex_sources = {}
        for vert in xmlmesh.findall(tag('vertices')):
            pos = next((e for e in vert if e.get('semantic') == 'POSITION'), None)
            if pos is not None:
                vertex_sources[vert.get('id')] = sources.get(pos.get('source', '').lstrip('#'))
        for group in list(xmlmesh):
            kind = group.tag.rsplit('}', 1)[-1]
            if kind not in {'polylist', 'polygons', 'trifans', 'tristrips', 'linestrips'}:
                continue
            inputs = group.findall(tag('input'))
            stride = 1 + max(int(e.get('offset', 0)) for e in inputs)
            if stride < 1 or stride > 64:
                raise ValueError('Invalid COLLADA primitive stride')
            vert_input = next((e for e in inputs if e.get('semantic') == 'VERTEX'), None)
            if vert_input is None:
                raise ValueError('COLLADA polygon is missing VERTEX input')
            positions = vertex_sources.get(vert_input.get('source', '').lstrip('#'))
            offset = int(vert_input.get('offset', 0))
            polygons = [np.fromstring(p.text or '', sep=' ', dtype=np.int64).reshape(-1, stride) for p in group.findall(tag('p'))]
            if kind == 'polylist':
                counts = [int(n) for n in group.findtext(tag('vcount'), '').split()]
                flat = np.concatenate(polygons) if polygons else np.empty((0, stride), dtype=np.int64)
                if min(counts, default=0) < 0 or sum(counts) != len(flat):
                    raise ValueError('Invalid COLLADA polygon counts')
                starts = np.cumsum([0] + counts)
                polygons = [flat[a:b] for a,b in zip(starts[:-1], starts[1:])]
            if group.find(tag('ph')) is not None:
                raise ValueError('COLLADA polygons with holes are unsupported')
            out = []
            for corners in polygons:
                if len(corners) < (2 if kind == 'linestrips' else 3):
                    continue
                ids = corners[:, offset]
                if positions is None or ids.min() < 0 or ids.max() >= len(positions):
                    raise ValueError('COLLADA polygon index is out of bounds')
                if kind == 'linestrips':
                    triangles = [[i, i + 1] for i in range(len(corners) - 1)]
                elif kind == 'tristrips':
                    triangles = [[i + 1, i, i + 2] if i % 2 else [i, i + 1, i + 2] for i in range(len(corners) - 2)]
                elif kind == 'trifans':
                    triangles = [[0, i, i + 1] for i in range(1, len(corners) - 1)]
                else:
                    points = [Vector(p[:3]) for p in positions[ids]]
                    lookup = {tuple(v): i for i,v in enumerate(points)}
                    triangles = [[int(v) if isinstance(v, int) else lookup[tuple(v)] for v in tri]
                                 for tri in tessellate_polygon([points])]
                out.extend(corners[tri].reshape(-1).tolist() for tri in triangles)
            group.tag = tag('lines' if kind == 'linestrips' else 'triangles')
            group.set('count', str(len(out)))
            for child in list(group):
                if child.tag != tag('input'):
                    group.remove(child)
            ET.SubElement(group, tag('p')).text = ' '.join(str(i) for row in out for i in row)


def read_dae(path):
    raise NotImplementedError("This add-on exports stadium DAE only")
    if Path(path).stat().st_size > 512 * 1024 * 1024:
        raise ValueError('COLLADA file exceeds 512 MiB')
    raw = Path(path).read_bytes()
    if len(raw) > 512 * 1024 * 1024:
        raise ValueError('COLLADA file exceeds 512 MiB')
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('COLLADA documents with DTD/entity declarations are unsupported')
    root = ET.fromstring(raw)
    if root.tag.rsplit('}', 1)[-1] != 'COLLADA':
        raise ValueError('This is not a COLLADA document')
    # Normalize supported COLLADA namespace revisions for the native geometry reader.
    for e in root.iter():
        e.tag = tag(e.tag.rsplit('}', 1)[-1])
    if root.find('.//' + tag('instance_controller')) is not None:
        raise ValueError('Skinned/animated COLLADA controllers are unsupported; export static mesh geometry first')
    _prepare_meshes(root)
    geometries = sorted(root.findall('./' + tag('library_geometries') + '/' + tag('geometry')), key=lambda e: e.get('id', ''))
    channels = [_xml_channels(g) for g in geometries]
    data = cdae_native.parse_dae_bytes(ET.tostring(root, encoding='utf-8'))
    mesh_by_id = {e.get('id'): (i, e) for i, e in enumerate(geometries)}
    materials = root.findall('./' + tag('library_materials') + '/' + tag('material'))
    mat_by_id = {e.get('id'): i for i, e in enumerate(materials)}
    active = root.find('./' + tag('scene') + '/' + tag('instance_visual_scene'))
    scene_id = active.get('url', '').lstrip('#') if active is not None else ''
    scenes = root.findall('./' + tag('library_visual_scenes') + '/' + tag('visual_scene'))
    scene = next((s for s in scenes if s.get('id') == scene_id), scenes[0] if scenes else None)
    meter = float(data.get('unit_meter', 1.0))
    if not math.isfinite(meter) or meter <= 0:
        raise ValueError('Invalid COLLADA unit scale')
    for i, geo in enumerate(geometries):
        mesh = data['meshes'][i]
        mesh.update(channels[i])
        editor = geo.find('./' + tag('extra') + '/' + tag('technique') + '[@profile="BLENDER_BEAMNG"]/' + tag('editor_mesh'))
        if editor is not None and editor.text:
            mesh['editor_mesh'] = decode_editor_mesh(editor.text)
        if geo.find('.//' + tag('input') + '[@semantic="NORMAL"]') is None:
            mesh.pop('normals', None)
        if mesh.get('line_verts') is not None:
            mesh['line_verts'] = np.asarray(mesh['line_verts']) * meter
        # Upstream omits a geometry that consists entirely of <lines>.
        if mesh.get('is_null') and geo.find('./' + tag('mesh') + '/' + tag('lines')) is not None:
            xm = geo.find(tag('mesh'))
            arrays = {s.get('id'): np.fromstring(s.findtext(tag('float_array'), ''), sep=' ', dtype=np.float32)
                      for s in xm.findall(tag('source'))}
            vertices = {v.get('id'): next(e.get('source', '').lstrip('#') for e in v if e.get('semantic') == 'POSITION') for v in xm.findall(tag('vertices'))}
            pairs, coords = [], []
            for line in xm.findall(tag('lines')):
                inp = line.find(tag('input'))
                values = arrays[vertices[inp.get('source', '').lstrip('#')]].reshape(-1, 3)
                indices = np.fromstring(line.findtext(tag('p'), ''), sep=' ', dtype=np.int64).reshape(-1, 2)
                pairs.extend((indices + len(coords)).tolist()); coords.extend(values.tolist())
            mesh.update(is_null=False, vertices=np.empty((0, 3), dtype=np.float32),
                        line_verts=np.asarray(coords, dtype=np.float32) * meter, line_indices=np.asarray(pairs, dtype=np.int32))
    asset_axis = root.findtext('./' + tag('asset') + '/' + tag('up_axis'), 'Y_UP').strip()
    axis = {'Z_UP': Matrix.Identity(4), 'Y_UP': Matrix.Rotation(math.pi / 2, 4, 'X'),
            'X_UP': Matrix.Rotation(-math.pi / 2, 4, 'Y')}.get(asset_axis)
    if axis is None:
        raise ValueError(f'Unsupported COLLADA up_axis {asset_axis}')
    nodes, objects, names, meshes = [], [], [], []
    library_nodes = {e.get('id'): e for e in root.findall('.//' + tag('node')) if e.get('id')}

    def visit(e, parent=-1, stack=()):
        identity = id(e)
        if identity in stack or len(stack) > 128:
            raise ValueError('Cyclic or excessively nested COLLADA node instances')
        name = e.get('name') or e.get('id') or 'Node'
        m = _matrix(e)
        m.translation *= meter
        if parent < 0:
            m = axis @ m
        ni = len(nodes)
        nodes.append({'name': name, 'parent_index': parent, 'matrix': [list(row) for row in m]})
        instances = e.findall(tag('instance_geometry'))
        for gi, instance in enumerate(instances):
            gid = instance.get('url', '').lstrip('#')
            if gid not in mesh_by_id:
                raise ValueError(f'Missing COLLADA geometry {gid}')
            mi, geo = mesh_by_id[gid]
            mesh = dict(data['meshes'][mi])
            bindings = {b.get('symbol'): mat_by_id.get(b.get('target', '').lstrip('#'), 1 << 28)
                        for b in instance.findall('.//' + tag('instance_material'))}
            groups = [g for g in geo.find(tag('mesh')) if g.tag.rsplit('}', 1)[-1] in ('triangles', 'polylist', 'polygons')]
            if mesh.get('primitives') is not None:
                mesh['primitives'] = np.array(mesh['primitives'], dtype=np.uint32, copy=True)
                for pi, group in enumerate(groups):
                    if pi < len(mesh['primitives']):
                        symbol = group.get('material')
                        index = bindings.get(symbol, mat_by_id.get(symbol, 1 << 28)) if symbol else 1 << 28
                        mesh['primitives'][pi, 2] = index
            mesh['source_extra'] = [ET.tostring(x, encoding='unicode') for x in e.findall(tag('extra'))]
            name_index = len(names)
            names.append(name if len(instances) == 1 else name + '_' + str(gi))
            objects.append({'name_index': name_index, 'num_meshes': 1, 'start_mesh': len(meshes), 'node_index': ni})
            meshes.append(mesh)
        for child in e:
            if child.tag == tag('node'):
                visit(child, ni, stack + (identity,))
            elif child.tag == tag('instance_node'):
                ref = library_nodes.get(child.get('url', '').lstrip('#'))
                if ref is None:
                    raise ValueError('Missing instance_node target')
                visit(ref, ni, stack + (identity,))
    if scene is not None:
        for e in scene.findall(tag('node')):
            visit(e)
    else:
        for mi, geo in enumerate(geometries):
            name = geo.get('name') or geo.get('id') or 'Mesh'
            nodes.append({'name': name, 'parent_index': -1, 'matrix': [list(r) for r in axis]})
            names.append(name); meshes.append(data['meshes'][mi])
            objects.append({'name_index': mi, 'num_meshes': 1, 'start_mesh': mi, 'node_index': mi})
    data.update(nodes=nodes, objects=objects, names=names, meshes=meshes)
    data['cache_metadata'] = {'source_format': 'COLLADA', 'source_up_axis': asset_axis, 'source_unit_meter': meter,
                              'has_animations': root.find(tag('library_animations')) is not None}
    return data


def normalize_cache(data):
    """Expand draw strips/fans without welding or changing triangle winding."""
    for mesh in data['meshes']:
        if mesh.get('is_null'):
            continue
        idx = np.asarray(mesh['indices'], dtype=np.int64)
        verts = np.asarray(mesh['vertices'])
        if not np.isfinite(verts).all():
            raise ValueError('Non-finite cache vertices')
        triangles, prims, cursor = [], [], 0
        for start, length, info in mesh['primitives']:
            start, length, info = int(start), int(length), int(info)
            if start < 0 or length < 0 or start + length > len(idx):
                raise ValueError('Cache primitive indices out of bounds')
            part = idx[start:start + length] if info & (1 << 29) else np.arange(start, start + length)
            kind = (info >> 30) & 3
            if kind == 0:
                if len(part) % 3:
                    raise ValueError('Invalid triangle-list length')
                tri = part.reshape(-1, 3)
            elif kind == 1:
                tri = np.array([[part[j + 1], part[j], part[j + 2]] if j % 2 else [part[j], part[j + 1], part[j + 2]] for j in range(len(part) - 2)], dtype=np.int64).reshape(-1, 3)
            elif kind == 2:
                tri = np.array([[part[0], part[j], part[j + 1]] for j in range(1, len(part) - 1)], dtype=np.int64).reshape(-1, 3)
            else:
                raise ValueError('Unsupported cache draw primitive')
            if tri.size and (tri.min() < 0 or tri.max() >= len(verts)):
                raise ValueError('Cache vertex index out of bounds')
            triangles.append(tri.reshape(-1))
            prims.append([cursor, tri.size, info & 0x1fffffff])
            cursor += tri.size
        mesh['indices'] = np.concatenate(triangles).astype(np.uint32) if triangles else np.empty(0, dtype=np.uint32)
        mesh['primitives'] = np.asarray(prims, dtype=np.uint32).reshape(-1, 3)
    return data


def read_shape(path):
    return normalize_cache(read_cache(path)) if str(path).lower().endswith('.cdae') else read_dae(path)


def build_hierarchy(builder, data, mesh_objects):
    nodes, entries = data.get('nodes', []), data.get('objects', [])
    by_node = {}
    for entry in entries:
        for slot in range(entry['num_meshes']):
            mi = entry['start_mesh'] + slot
            obj = mesh_objects.get(mi)
            if obj is not None:
                by_node.setdefault(entry['node_index'], []).append(obj)
                obj['beamng_source_name'] = data['names'][entry['name_index']]
                if entry['num_meshes'] > 1:
                    obj.name += '_LOD' + str(slot)
                    obj['beamng_lod_slot'] = slot
    col = builder._get_import_collection() if builder.use_collection else builder.context.collection
    anchors = {}
    for i, n in enumerate(nodes):
        obs = by_node.get(i, [])
        if len(obs) == 1:
            anchors[i] = obs[0]
        else:
            anchor = bpy.data.objects.new(n.get('name', 'Node'), None)
            col.objects.link(anchor)
            anchors[i] = anchor
            for obj in obs:
                obj.parent = anchor
    for i, n in enumerate(nodes):
        obj = anchors[i]
        parent = n.get('parent_index', -1)
        if parent >= len(nodes) or parent == i:
            raise ValueError('Invalid node hierarchy')
        if parent >= 0:
            # Reject cycles before assigning a Blender parent.
            seen, j = {i}, parent
            while j >= 0:
                if j in seen or j >= len(nodes):
                    raise ValueError('Cyclic node hierarchy')
                seen.add(j); j = nodes[j].get('parent_index', -1)
            obj.parent = anchors[parent]
        if 'matrix' in n:
            m = Matrix(n['matrix'])
        else:
            from mathutils import Quaternion
            q = n.get('quaternion', [0, 0, 0, 1])
            m = Matrix.LocRotScale(Vector(n.get('translation', (0, 0, 0))),
                                   Quaternion((q[3], q[0], q[1], q[2])), Vector(n.get('scale', (1, 1, 1))))
        m.translation *= builder.global_scale
        obj.matrix_parent_inverse = Matrix.Identity(4)
        obj.matrix_basis = m
        if obj.type != 'MESH':
            obj['beamng_source_name'] = n.get('name', obj.name)
        obj['beamng_display_name'] = obj.name
    for mi, obj in mesh_objects.items():
        obj['beamng_source_file'] = str(builder.filepath)
        obj['beamng_source_name'] = obj.get('beamng_source_name', obj.name)
        obj['beamng_display_name'] = obj.name
        if data['meshes'][mi].get('source_extra'):
            obj['beamng_dae_extra'] = json.dumps(data['meshes'][mi]['source_extra'])
    metadata = json.dumps(data.get('cache_metadata', {}), ensure_ascii=False)
    if builder.use_collection:
        col['beamng_source_metadata'] = metadata
    else:
        for obj in mesh_objects.values():
            obj['beamng_source_metadata'] = metadata
    from .cache_layout import remember_layout
    remember_layout(data, mesh_objects)
    builder.context.view_layer.update()


def finish_dae(path, data, export_objects, scale, static_stadium=False):
    """Keep the native mesh writer, write exact matrices and hierarchy in XML."""
    tree = ET.parse(path); root = tree.getroot()
    geometries = root.findall('./' + tag('library_geometries') + '/' + tag('geometry'))
    material_ids = [e.get('id') for e in root.findall('./' + tag('library_materials') + '/' + tag('material'))]
    lib = root.find(tag('library_visual_scenes'))
    lib.clear()
    scene = ET.SubElement(lib, tag('visual_scene'), {'id': 'BeamNGScene', 'name': 'Scene'})
    inst = root.find('./' + tag('scene') + '/' + tag('instance_visual_scene'))
    inst.set('url', '#BeamNGScene')
    wanted = set(export_objects)
    for obj in export_objects:
        parent = obj.parent
        while parent:
            wanted.add(parent); parent = parent.parent
    elements = {}
    mesh_index = {obj: i for i, obj in enumerate(export_objects)}
    def emit(obj):
        if obj in elements:
            return elements[obj]
        parent = emit(obj.parent) if obj.parent in wanted else scene
        node = ET.SubElement(parent, tag('node'), {'id': 'BeamNGNode_' + str(len(elements)), 'name': source_name(obj), 'type': 'NODE'})
        elements[obj] = node
        m = obj.matrix_local.copy() if obj.parent in wanted else obj.matrix_world.copy()
        m.translation *= scale
        ET.SubElement(node, tag('matrix'), {'sid': 'transform'}).text = ' '.join(format(a, '.9g') for row in m for a in row)
        if obj in mesh_index:
            i = mesh_index[obj]
            geo = geometries[i]
            geo.set('name', obj.get('dae_geometry_name', obj.data.name))
            ins = ET.SubElement(node, tag('instance_geometry'), {'url': '#' + geo.get('id')})
            tc = ET.SubElement(ET.SubElement(ins, tag('bind_material')), tag('technique_common'))
            groups = list(geo.find(tag('mesh')))
            for g in groups:
                symbol = g.get('material')
                if symbol:
                    # Native geometry groups use material names as their symbols.
                    j = int(symbol[4:]) if symbol.startswith('mat_') and symbol[4:].isdigit() else None
                    if j is not None and j < len(material_ids):
                        im = ET.SubElement(tc, tag('instance_material'), {'symbol': symbol, 'target': '#' + material_ids[j]})
                        for ui, name in enumerate(data['meshes'][i].get('tvert_names', [])):
                            ET.SubElement(im, tag('bind_vertex_input'), {'semantic': name, 'input_semantic': 'TEXCOORD', 'input_set': str(ui)})
            if obj.get('beamng_dae_extra'):
                for text in json.loads(obj['beamng_dae_extra']):
                    node.append(ET.fromstring(text))
        return node
    for obj in export_objects:
        emit(obj)
    profile = None
    if static_stadium:
        from .static_shape import apply_static_profile
        profile = apply_static_profile(root)
    tree.write(path, encoding='utf-8', xml_declaration=True)
    return profile


def write_dae(path, data, objects, scale, static_stadium=False):
    """Write standards-based XML with unique IDs and float32 round-trip precision."""
    from datetime import datetime, timezone
    root = ET.Element(tag('COLLADA'), {'version': '1.4.1'})
    asset = ET.SubElement(root, tag('asset'))
    contributor = ET.SubElement(asset, tag('contributor'))
    ET.SubElement(contributor, tag('authoring_tool')).text = 'BeamNG Collada Importer/Exporter 1.4.2; Blender ' + bpy.app.version_string
    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    for name in ('created', 'modified'):
        ET.SubElement(asset, tag(name)).text = stamp
    ET.SubElement(asset, tag('unit'), {'name': 'meter', 'meter': '1'})
    ET.SubElement(asset, tag('up_axis')).text = 'Z_UP'
    effects = ET.SubElement(root, tag('library_effects'))
    mats = ET.SubElement(root, tag('library_materials'))
    for i, m in enumerate(data['materials']):
        effect = ET.SubElement(effects, tag('effect'), {'id': f'fx_{i}'})
        common = ET.SubElement(effect, tag('profile_COMMON'))
        technique = ET.SubElement(common, tag('technique'), {'sid': 'common'})
        phong = ET.SubElement(technique, tag('phong'))
        diffuse = ET.SubElement(phong, tag('diffuse'))
        ET.SubElement(diffuse, tag('color'), {'sid': 'diffuse'}).text = ' '.join(format(float(v), '.9g') for v in m.get('base_color', [.8, .8, .8, 1]))
        shininess = ET.SubElement(phong, tag('shininess'))
        ET.SubElement(shininess, tag('float')).text = str(1000 * (1 - float(m.get('roughness', .5))))
        reflectivity = ET.SubElement(phong, tag('reflectivity'))
        ET.SubElement(reflectivity, tag('float')).text = str(float(m.get('metallic', 0)))
        ior = ET.SubElement(phong, tag('index_of_refraction'))
        ET.SubElement(ior, tag('float')).text = str(float(m.get('ior', 1.45)))
        mat = ET.SubElement(mats, tag('material'), {'id': f'mat_{i}', 'name': m['name']})
        ET.SubElement(mat, tag('instance_effect'), {'url': f'#fx_{i}'})
    library = ET.SubElement(root, tag('library_geometries'))
    for i, mesh in enumerate(data['meshes']):
        geo = ET.SubElement(library, tag('geometry'), {'id': f'geo_{i}', 'name': objects[i].data.name})
        xmlmesh = ET.SubElement(geo, tag('mesh'))
        channels = []
        def source(name, values, width, params, semantic, set_index=None):
            sid = f'geo_{i}_{name}'
            a = np.asarray(values, dtype=np.float32).reshape(-1, width)
            if not np.isfinite(a).all():
                raise ValueError('Non-finite COLLADA export attribute')
            src = ET.SubElement(xmlmesh, tag('source'), {'id': sid})
            if semantic == 'TEXCOORD':
                labels = mesh.get('tvert_names', [])
                src.set('name', labels[set_index] if set_index < len(labels) else f'UV{set_index}')
            elif semantic == 'COLOR':
                labels = mesh.get('color_layer_names', [])
                src.set('name', labels[set_index] if set_index < len(labels) else f'Color{set_index}')
            array_id = sid + '_array'
            ET.SubElement(src, tag('float_array'), {'id': array_id, 'count': str(a.size)}).text = ' '.join(format(float(v), '.9g') for v in a.reshape(-1))
            common = ET.SubElement(src, tag('technique_common'))
            acc = ET.SubElement(common, tag('accessor'), {'source': '#' + array_id, 'count': str(len(a)), 'stride': str(width)})
            for param in params:
                ET.SubElement(acc, tag('param'), {'name': param, 'type': 'float'})
            inp = {'semantic': semantic, 'source': '#' + sid, 'offset': '0'}
            if set_index is not None:
                inp['set'] = str(set_index)
            channels.append(inp)
        source('positions', mesh.get('vertices', mesh.get('line_verts', [])), 3, 'XYZ', 'POSITION')
        if mesh.get('normals') is not None:
            source('normals', mesh['normals'], 3, 'XYZ', 'NORMAL')
        for ui, uv in enumerate([mesh.get('uv0'), mesh.get('uv1')] + list(mesh.get('uv_extra', []))):
            if uv is not None:
                a = np.asarray(uv).copy(); a[:, 1] = 1 - a[:, 1]
                source('uv_' + str(ui), a, 2, 'ST', 'TEXCOORD', ui)
        colors = mesh.get('color_layers') or ([mesh['colors']] if mesh.get('colors') is not None else [])
        for ci, color in enumerate(colors):
            a = np.asarray(color)
            source('color_' + str(ci), a.astype(np.float32) / (255. if a.dtype == np.uint8 else 1.), 4, 'RGBA', 'COLOR', ci)
        vertices = ET.SubElement(xmlmesh, tag('vertices'), {'id': f'geo_{i}_vertices'})
        ET.SubElement(vertices, tag('input'), {'semantic': 'POSITION', 'source': f'#geo_{i}_positions'})
        channels[0] = {'semantic': 'VERTEX', 'source': f'#geo_{i}_vertices', 'offset': '0'}
        idx = np.asarray(mesh.get('indices', []), dtype=np.int64)
        for start, length, info in mesh.get('primitives', []):
            start, length, info = int(start), int(length), int(info)
            part = idx[start:start + length].reshape(-1, 3)[:, ::-1]
            attrs = {'count': str(len(part))}
            if data['materials'] and not info & (1 << 28):
                attrs['material'] = 'mat_' + str(info & 0xfffffff)
            triangles = ET.SubElement(xmlmesh, tag('triangles'), attrs)
            for channel in channels:
                ET.SubElement(triangles, tag('input'), channel)
            ET.SubElement(triangles, tag('p')).text = ' '.join(str(int(v)) for v in part.reshape(-1))
        lines = mesh.get('line_indices')
        if lines is not None:
            # Loose edges have a separate source position buffer.
            channels_before = len(channels)
            source('line_positions', mesh['line_verts'] * scale, 3, 'XYZ', 'POSITION')
            line_vertices = ET.SubElement(xmlmesh, tag('vertices'), {'id': f'geo_{i}_line_vertices'})
            ET.SubElement(line_vertices, tag('input'), {'semantic': 'POSITION', 'source': f'#geo_{i}_line_positions'})
            xml_lines = ET.SubElement(xmlmesh, tag('lines'), {'count': str(len(lines))})
            ET.SubElement(xml_lines, tag('input'), {'semantic': 'VERTEX', 'source': f'#geo_{i}_line_vertices', 'offset': '0'})
            ET.SubElement(xml_lines, tag('p')).text = ' '.join(str(int(v)) for v in np.asarray(lines).reshape(-1))
        # COLLADA schema orders sources before vertices and primitives.
        xmlmesh[:] = ([c for c in xmlmesh if c.tag == tag('source')]
                      + [c for c in xmlmesh if c.tag == tag('vertices')]
                      + [c for c in xmlmesh if c.tag not in {tag('source'), tag('vertices')}])
        if mesh.get('editor_mesh') is not None:
            # The native DAE reader expands XML corners in their written order.
            # Keep source identities aligned with that buffer, rather than the
            # cache-oriented winding used by the extractor.
            editor = dict(mesh['editor_mesh'])
            order = np.concatenate([idx[int(start):int(start) + int(length)].reshape(-1, 3)[:, ::-1].reshape(-1)
                                    for start, length, info in mesh.get('primitives', [])]) if len(idx) else np.empty(0, dtype=np.int64)
            ids = np.frombuffer(editor['vertex_ids'], dtype='<u4')
            editor['vertex_ids'] = ids[order].tobytes()
            extra = ET.SubElement(geo, tag('extra'))
            technique = ET.SubElement(extra, tag('technique'), {'profile': 'BLENDER_BEAMNG'})
            ET.SubElement(technique, tag('editor_mesh'), {'encoding': 'base64-zstd-msgpack', 'version': '1'}).text = encode_editor_mesh(editor)
    ET.SubElement(root, tag('library_visual_scenes'))
    scene = ET.SubElement(root, tag('scene'))
    ET.SubElement(scene, tag('instance_visual_scene'), {'url': '#BeamNGScene'})
    ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)
    return finish_dae(path, data, objects, scale, static_stadium=static_stadium)


def bake_cache_transforms(data, objects, scale):
    """Cache default nodes have no scale/shear; bake linear world transforms."""
    for i, obj in enumerate(objects):
        m = np.asarray(obj.matrix_world, dtype=np.float64)
        mesh = data['meshes'][i]
        linear = m[:3, :3]
        if not mesh.get('is_null'):
            mesh['vertices'] = np.asarray(mesh['vertices']) @ linear.T
            if np.linalg.det(linear) < 0:
                # A mirrored Blender object carries a handedness correction.
                # A baked cache has no such object matrix, so reverse the faces.
                mesh['indices'] = np.asarray(mesh['indices']).reshape(-1, 3)[:, [0, 2, 1]].reshape(-1).copy()
            if mesh.get('normals') is not None:
                normal = np.asarray(mesh['normals']) @ np.linalg.pinv(linear)
                lengths = np.linalg.norm(normal, axis=1, keepdims=True)
                mesh['normals'] = np.divide(normal, lengths, out=np.zeros_like(normal), where=lengths > 1e-20).astype(np.float32)
        data['nodes'][i].update(translation=(m[:3, 3] * scale).tolist(), quaternion=[0, 0, 0, 1], scale=[1, 1, 1])
