# SPDX-License-Identifier: GPL-3.0-or-later
"""Opt-in BeamNG PBR packages. Bake UV-only graphs in an isolated scene.

No source nodes, images, UVs, visibility or selection are edited. Unsupported
graphs fail before publication; this is not a Frostbite shader translator.
"""
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
import hashlib
import json
import math
import re
import struct
import zlib
import bpy
import numpy as np
from .planar_atlas import planar_uv

CHANNELS = ('Base Color', 'Roughness', 'Metallic', 'Alpha', 'Normal', 'Emission Color', 'Emission Strength',
            'Coat Weight', 'Coat Roughness')
ALLOWED = {'RGB', 'VALUE', 'TEX_IMAGE', 'UVMAP', 'TEX_COORD', 'MIX_RGB', 'MIX',
           'MATH', 'VECT_MATH', 'MAPPING', 'VECTOR_ROTATE', 'SEPARATE_COLOR',
           'COMBINE_COLOR', 'SEPXYZ', 'COMBXYZ', 'VALTORGB', 'CLAMP', 'MAP_RANGE',
           'INVERT', 'GAMMA', 'HUE_SAT', 'BRIGHTCONTRAST', 'RGBTOBW', 'NORMAL_MAP', 'REROUTE'}


def virtual_directory(destination, override=''):
    """Derive BeamNG VFS path, never emit an absolute Windows texture path."""
    if override.strip():
        value = override.strip().replace('\\', '/')
    else:
        parts = Path(destination).parent.parts
        starts = [i for i, part in enumerate(parts) if part.lower() in {'levels', 'vehicles', 'art'}]
        if not starts:
            raise ValueError('Material Package: export inside a levels/vehicles/art folder, or set Game Texture Directory (for example /levels/my_level/art/stadium)')
        value = '/' + '/'.join(parts[starts[0]:])
    path = PurePosixPath(value)
    if not value.startswith('/') or value.startswith('//') or ':' in value or any(p in {'.', '..'} for p in value.split('/')):
        raise ValueError('Game Texture Directory must be a /levels/..., /vehicles/... or /art/... path without ..')
    if len(path.parts) < 3 or path.parts[1] not in {'levels', 'vehicles', 'art'}:
        raise ValueError('Game Texture Directory must start with /levels/, /vehicles/ or /art/')
    return str(path).rstrip('/')


def principled(material):
    if not material.use_nodes or not material.node_tree:
        return None
    outputs = [n for n in material.node_tree.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output]
    if len(outputs) != 1:
        raise ValueError('requires one active Material Output')
    output = outputs[0]
    if output.inputs['Volume'].is_linked or output.inputs['Displacement'].is_linked:
        raise ValueError('volume/displacement needs an object bake')
    surface = output.inputs['Surface']
    if not surface.is_linked or surface.links[0].from_node.type != 'BSDF_PRINCIPLED':
        raise ValueError('surface must connect directly to Principled BSDF')
    return surface.links[0].from_node


def inspect_material(material, allow_glass=False, allow_object=False, allow_sheen=True):
    bsdf = principled(material)
    if bsdf is None:
        return dict(uv_names=[], needs_uv=False, periodic=True, warnings=['Uses viewport PBR values (no node material)'])
    transmission = bsdf.inputs['Transmission Weight']
    glass = transmission.is_linked or float(transmission.default_value) > 1e-6
    sheen = bsdf.inputs.get('Sheen Weight')
    sheen_weight = float(sheen.default_value) if sheen and not sheen.is_linked else 0.
    if sheen and sheen.is_linked:
        raise ValueError('linked Sheen Weight needs a dedicated BeamNG material')
    if sheen_weight > 1e-6 and not allow_sheen:
        raise ValueError('Sheen Weight: enable Approximate Sheen to retain base PBR without the cloth lobe')
    coat_roughness = bsdf.inputs.get('Coat Roughness')
    if coat_roughness and coat_roughness.is_linked:
        raise ValueError('linked Coat Roughness needs a dedicated BeamNG material')
    for name in ('Transmission Weight', 'Subsurface Weight', 'Anisotropic', 'Thin Film Thickness'):
        if name == 'Transmission Weight' and allow_glass:
            continue
        socket = bsdf.inputs.get(name)
        if socket and (socket.is_linked or abs(float(socket.default_value)) > 1e-6):
            if name == 'Transmission Weight':
                raise ValueError('Transmission Weight: enable Approximate Glass for a transparent BeamNG preview (no refraction)')
            raise ValueError(f'{name} needs a dedicated BeamNG material')
    if material.node_tree.animation_data and (material.node_tree.animation_data.action or material.node_tree.animation_data.drivers):
        raise ValueError('animated/driven material requires a chosen static snapshot')
    visited, uv_names, needs_uv, periodic, object_required, implicit_uv = set(), set(), False, True, False, False
    color_names = set()
    def walk(socket):
        nonlocal needs_uv, periodic, object_required, implicit_uv
        for link in socket.links:
            node = link.from_node
            key = (node.as_pointer(), link.from_socket.identifier)
            if key in visited:
                continue
            visited.add(key)
            if node.type in {'VERTEX_COLOR', 'ATTRIBUTE'} and allow_object and not node.mute:
                name = node.layer_name if node.type == 'VERTEX_COLOR' else node.attribute_name
                if not name or (node.type == 'ATTRIBUTE' and node.attribute_type not in {'GEOMETRY', 'INSTANCER'}):
                    raise ValueError(f'{node.name}: requires a named mesh color attribute')
                color_names.add(name)
                object_required = True
                continue
            if node.type == 'NEW_GEOMETRY' and allow_object and link.from_socket.name in {'Position', 'Normal', 'True Normal'}:
                object_required = True
                continue
            if node.type not in ALLOWED or node.mute:
                raise ValueError(f'{node.name} ({node.type}) needs an object/special-shader bake')
            if node.type == 'TEX_COORD':
                if link.from_socket.name != 'UV':
                    raise ValueError(f'{node.name}: {link.from_socket.name} coordinates need an object bake')
                needs_uv = True
                implicit_uv = True
            if node.type == 'UVMAP':
                if node.from_instancer:
                    raise ValueError('instancer UV coordinates need an object bake')
                needs_uv = True
                if node.uv_map:
                    uv_names.add(node.uv_map)
                else:
                    implicit_uv = True
            if node.type == 'NORMAL_MAP':
                if node.space != 'TANGENT':
                    raise ValueError('only tangent-space Normal Map nodes are supported')
                if node.uv_map:
                    uv_names.add(node.uv_map)
                else:
                    implicit_uv = True
                needs_uv = True
            if node.type == 'TEX_IMAGE':
                image = node.image
                if not image or image.source not in {'FILE', 'GENERATED'} or image.type not in {'IMAGE', 'UV_TEST'}:
                    raise ValueError(f'{node.name}: requires a still image (movies/sequences/UDIM need a separate conversion)')
                if image.source == 'FILE' and not image.packed_file and not Path(bpy.path.abspath(image.filepath, library=image.library)).resolve().is_file():
                    raise ValueError(f'{image.name}: texture file is missing')
                if not image.size[0] or not image.size[1]:
                    raise ValueError(f'{image.name}: texture could not be decoded')
                if node.projection != 'FLAT':
                    raise ValueError(f'{node.name}: {node.projection} projection needs an object bake')
                vector = node.inputs['Vector']
                implicit_uv = implicit_uv or not vector.is_linked
                direct_uv = not vector.is_linked or vector.links[0].from_node.type in {'UVMAP', 'TEX_COORD'}
                periodic = periodic and node.extension == 'REPEAT' and direct_uv
                needs_uv = True
            for value in node.inputs:
                walk(value)
    for name in CHANNELS:
        walk(bsdf.inputs[name])
    if glass and allow_glass:
        walk(transmission)
    # Raw UV/math output is not necessarily periodic, even without image nodes.
    for node in material.node_tree.nodes:
        if node.type in {'UVMAP', 'TEX_COORD'}:
            for out in node.outputs:
                for link in out.links:
                    if link.to_node.type != 'TEX_IMAGE':
                        periodic = False
    if len(uv_names) > 1:
        if not allow_object:
            raise ValueError('combines different UV maps; requires an object bake')
        object_required = True
    warnings = ['Glass transmission approximated with BeamNG opacity; refraction is not preserved'] if glass else []
    if sheen_weight > 1e-6:
        warnings.append('Blender sheen cloth lobe is unavailable in BeamNG; base color and roughness are retained')
    if bsdf.inputs['Emission Strength'].is_linked or bsdf.inputs['Emission Strength'].default_value != 0:
        warnings.append('Emission brightness uses the chosen nits-per-strength conversion; engine lighting may differ')
    return dict(uv_names=sorted(uv_names), color_names=sorted(color_names), needs_uv=needs_uv, periodic=periodic, object_required=object_required,
                glass=glass, implicit_uv=implicit_uv, source_sheen_weight=sheen_weight, warnings=warnings)


def validate_uvs(data, index, plan):
    if not plan['needs_uv']:
        return
    for mesh in data['meshes']:
        primitives = np.asarray(mesh.get('primitives', []))
        if not primitives.size:
            continue
        flags = primitives[:, 2].astype(np.uint32)
        used = ((flags & 0x0fffffff) == index) & ((flags & 0x10000000) == 0)
        if not used.any():
            continue
        names = mesh.get('tvert_names', [])
        if not names or (plan['uv_names'] and names[0] != plan['uv_names'][0]):
            raise ValueError(f'used texture UV must be exported as UV0 (requested {plan["uv_names"] or "active UV"}, exported {names})')
        all_uv = np.asarray(mesh.get('uv0', []))
        indices = np.asarray(mesh.get('indices', []), dtype=np.int64)
        chunks = [indices[int(row[0]):int(row[0]+row[1])] for row in primitives[used]]
        uv = all_uv[np.concatenate(chunks)] if all_uv.size and chunks else np.asarray([])
        if not uv.size:
            raise ValueError('textured faces have no UV coordinates')
        if not plan['periodic'] and (float(uv.min()) < -1e-5 or float(uv.max()) > 1.00001):
            raise ValueError('non-repeating shader with UV coordinates outside 0..1 needs an object bake')


def png_bytes(pixels, color=False):
    """Write straight-alpha PNG; explicitly encode linear RGB as sRGB for color maps."""
    values = np.array(pixels, dtype=np.float32, copy=True)
    if not np.isfinite(values).all():
        raise ValueError('Baked texture contains non-finite pixels')
    values = np.clip(values, 0, 1)
    if color:
        rgb = values[..., :3]
        values[..., :3] = np.where(rgb <= .0031308, rgb * 12.92, 1.055 * np.power(rgb, 1 / 2.4) - .055)
    raw = np.rint(values * 255).astype(np.uint8)[::-1]
    height, width, channels = raw.shape
    def chunk(kind, payload):
        return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload) & 0xffffffff)
    body = b''.join(b'\0' + row.tobytes() for row in raw)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6 if channels == 4 else 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(body, 6)) + chunk(b'IEND', b'')


@contextmanager
def baker(context, material, plan, resolution, geometry=None):
    scene = mesh = obj = copy = image = None
    try:
        scene = bpy.data.scenes.new('__BeamNG_MaterialBake')
        scene.render.engine = 'CYCLES'
        scene.cycles.device = 'CPU'; scene.cycles.samples = 1
        scene.render.threads_mode = 'FIXED'; scene.render.threads = 4
        mesh = bpy.data.meshes.new('__BeamNG_MaterialBake')
        if geometry is None:
            mesh.from_pydata([(0,0,0),(1,0,0),(1,1,0),(0,1,0)], [], [(0,1,2,3)])
            uv = mesh.uv_layers.new(name=(plan['uv_names'] or ['UVMap'])[0])
            for item, xy in zip(uv.data, [(0,0),(1,0),(1,1),(0,1)]): item.uv = xy
        else:
            vertices = geometry['vertices']
            mesh.from_pydata(vertices, [], np.arange(len(vertices)).reshape(-1,3))
            for name, values in geometry['uvs']:
                layer = mesh.uv_layers.new(name=name)
                layer.data.foreach_set('uv', np.asarray(values,dtype=np.float32).ravel())
            for name, values in geometry.get('colors', []):
                layer = mesh.color_attributes.new(name=name, type='FLOAT_COLOR', domain='CORNER')
                layer.data.foreach_set('color', np.asarray(values,dtype=np.float32).ravel())
            if geometry.get('normals') is not None:
                for face in mesh.polygons: face.use_smooth = True
                mesh.normals_split_custom_set(geometry['normals'])
            uv = mesh.uv_layers.new(name='__BeamNG_BakedUV')
            mesh.uv_layers.active_index = len(mesh.uv_layers)-1
            uv.active_render = True
        obj = bpy.data.objects.new('__BeamNG_MaterialBake', mesh); scene.collection.objects.link(obj)
        if geometry is not None:
            obj.matrix_world = geometry['matrix']
        obj.select_set(True, view_layer=scene.view_layers[0]); scene.view_layers[0].objects.active = obj
        copy = material.copy(); mesh.materials.append(copy)
        if not copy.use_nodes:
            copy.use_nodes = True
            p = principled(copy)
            p.inputs['Base Color'].default_value = material.diffuse_color
            p.inputs['Roughness'].default_value = material.roughness
            p.inputs['Metallic'].default_value = material.metallic
        p = principled(copy); nodes, links = copy.node_tree.nodes, copy.node_tree.links
        bake_uv_name = uv.name
        if geometry is not None:
            # Pin implicit source UVs before selecting the new destination atlas.
            source_uv = geometry['active_uv']
            for node in list(nodes):
                if node.type == 'ATTRIBUTE' and node.attribute_name in plan.get('color_names', []):
                    # Realize Instances propagates the instance's named color to
                    # the mesh. The isolated bake has no parent instancer.
                    node.attribute_type = 'GEOMETRY'
                if node.type == 'TEX_IMAGE' and not node.inputs['Vector'].is_linked:
                    pin = nodes.new('ShaderNodeUVMap'); pin.uv_map = source_uv
                    links.new(pin.outputs[0], node.inputs['Vector'])
                elif node.type == 'TEX_COORD':
                    pin = nodes.new('ShaderNodeUVMap'); pin.uv_map = source_uv
                    for link in list(node.outputs['UV'].links): links.new(pin.outputs[0], link.to_socket)
                elif node.type == 'UVMAP' and not node.uv_map:
                    node.uv_map = source_uv
                elif node.type == 'NORMAL_MAP' and not node.uv_map:
                    node.uv_map = source_uv
            continuous = planar_uv(vertices, resolution)
            if continuous is not None:
                uv.data.foreach_set('uv', continuous.ravel())
                geometry['atlas_method'] = 'Continuous planar (overlap checked)'
            else:
                geometry['atlas_method'] = 'Smart project triangle islands'
            with context.temp_override(scene=scene, view_layer=scene.view_layers[0], object=obj,
                                       active_object=obj, selected_objects=[obj], selected_editable_objects=[obj]):
                try:
                    if continuous is None:
                        bpy.ops.object.mode_set(mode='EDIT')
                        with context.temp_override(edit_object=obj, objects_in_mode=[obj], objects_in_mode_unique_data=[obj]):
                            bpy.ops.mesh.select_all(action='SELECT')
                            bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=.02)
                finally:
                    if obj.mode != 'OBJECT': bpy.ops.object.mode_set(mode='OBJECT')
            uv = mesh.uv_layers[bake_uv_name]  # Edit-mode reconstruction invalidates RNA layer handles.
        output = next(n for n in nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output)
        emission = nodes.new('ShaderNodeEmission')
        image = bpy.data.images.new('__BeamNG_MaterialBake', width=resolution, height=resolution, alpha=True, float_buffer=True)
        image.colorspace_settings.name = 'Non-Color'
        target = nodes.new('ShaderNodeTexImage'); target.image = image; nodes.active = target
        for node in nodes: node.select = node == target
        def sample(name):
            source = p.inputs[name]
            if name != 'Normal' and not source.is_linked:
                v = source.default_value
                rgb = [float(v)] * 3 if isinstance(v, (float, int)) else list(v)[:3]
                return np.broadcast_to(np.array(rgb + [1.], dtype=np.float32), (resolution, resolution, 4)).copy()
            for link in list(output.inputs['Surface'].links): links.remove(link)
            if name == 'Normal':
                # Opacity is exported separately; transparent BSDF samples would
                # otherwise erase normal data in the surface bake.
                for link in list(p.inputs['Alpha'].links): links.remove(link)
                p.inputs['Alpha'].default_value = 1
                for link in list(p.inputs['Transmission Weight'].links): links.remove(link)
                p.inputs['Transmission Weight'].default_value = 0
                links.new(p.outputs['BSDF'], output.inputs['Surface'])
            else:
                for link in list(emission.inputs['Color'].links): links.remove(link)
                links.new(source.links[0].from_socket, emission.inputs['Color'])
                links.new(emission.outputs[0], output.inputs['Surface'])
            with context.temp_override(scene=scene, view_layer=scene.view_layers[0], object=obj,
                                       active_object=obj, selected_objects=[obj], selected_editable_objects=[obj]):
                result = bpy.ops.object.bake(type='NORMAL' if name == 'Normal' else 'EMIT',
                         margin=4 if geometry is not None else 0, use_clear=True, use_selected_to_active=False, uv_layer=uv.name,
                         normal_space='TANGENT', normal_r='POS_X', normal_g='POS_Y', normal_b='POS_Z')
            if result != {'FINISHED'}:
                raise RuntimeError(f'{material.name}: {name} bake did not finish')
            values = np.empty(resolution * resolution * 4, dtype=np.float32)
            image.pixels.foreach_get(values)
            return values.reshape(resolution, resolution, 4)
        atlas = None
        if geometry is not None:
            atlas = np.empty(len(mesh.loops)*2,dtype=np.float32); uv.data.foreach_get('uv',atlas);atlas=atlas.reshape(-1,2)
        yield sample, p, atlas
    finally:
        if obj: bpy.data.objects.remove(obj, do_unlink=True)
        if mesh: bpy.data.meshes.remove(mesh)
        if copy: bpy.data.materials.remove(copy)
        if image: bpy.data.images.remove(image)
        if scene: bpy.data.scenes.remove(scene)


def _validate_package_settings(prepared, destination):
    """Validate output settings shared by preflight and the real package writer."""
    opts = prepared['options']
    destination = Path(destination)
    virtual = virtual_directory(destination, opts.get('game_directory', ''))
    resolution = int(opts.get('material_resolution', '1024'))
    if resolution not in {32, 64, 128, 256, 512, 1024, 2048, 4096}:
        raise ValueError('Unsupported material bake resolution')
    namespace = re.sub(r'[^A-Za-z0-9_]', '_', destination.stem)[:40]
    namespace += '_' + hashlib.sha256((virtual + '/' + destination.name).encode()).hexdigest()[:8]
    texture_folder = destination.parent / ('bmtex_' + hashlib.sha256(namespace.encode()).hexdigest()[:12])
    if texture_folder.is_symlink() or texture_folder.is_junction() or (texture_folder.exists() and not texture_folder.is_dir()):
        raise ValueError('Material texture destination is not a regular directory')
    return virtual, resolution, namespace, texture_folder


def _material_plans(prepared, mutate=False):
    """Inspect every exported material and its evaluated mesh assignments.

    With ``mutate`` false this is the fast, non-baking preflight used by the UI.
    With it true the same checked plan prepares per-object atlas jobs for the real
    writer. Keeping both paths here prevents a lightweight preflight from silently
    accepting graphs or UV/color requirements that the full export will reject.
    """
    opts, data = prepared['options'], prepared['data']
    sources = prepared['material_sources']
    plans, failures, originals = [], [], {}
    for index, entry in enumerate(list(data['materials'])):
        material = sources.get(entry['name'])
        try:
            if material is None:
                raise ValueError('source material was not captured')
            plan = inspect_material(material, opts.get('approximate_glass', False), opts.get('bake_object_materials', True),
                                    opts.get('approximate_sheen', True))
            object_bake = plan.get('object_required', False)
            try:
                validate_uvs(data, index, plan)
                if plan.get('implicit_uv'):
                    for mi, mesh in enumerate(data['meshes']):
                        prim = np.asarray(mesh.get('primitives', []))
                        if not prim.size: continue
                        flags = prim[:,2].astype(np.uint32)
                        if not np.any(((flags & 0x0fffffff) == index) & ((flags & 0x10000000) == 0)): continue
                        if prepared['active_uv_names'][mi] != (mesh.get('tvert_names') or [''])[0]:
                            raise ValueError('active source UV differs from exported UV0')
            except ValueError:
                if not opts.get('bake_object_materials', True): raise
                object_bake = True
            if not object_bake:
                plans.append((entry, material, plan, None, None))
            else:
                jobs = 0
                for mi, mesh in enumerate(data['meshes']):
                    primitives = np.asarray(mesh.get('primitives', []))
                    if not primitives.size: continue
                    flags = primitives[:,2].astype(np.uint32)
                    mask = ((flags & 0x0fffffff) == index) & ((flags & 0x10000000) == 0)
                    if not mask.any(): continue
                    layers = [mesh[k] for k in ('uv0','uv1') if k in mesh] + list(mesh.get('uv_extra', []))
                    if mutate:
                        if mi not in originals:
                            originals[mi] = [(n,a.copy()) for n,a in zip(mesh.get('tvert_names', []),layers)]
                        available = dict(originals[mi])
                    else:
                        available = dict(zip(mesh.get('tvert_names', []), layers))
                    if any(n not in available for n in plan['uv_names']):
                        raise ValueError('required source UV map was excluded; export all UV maps or include it in UV roles')
                    if plan.get('implicit_uv') and prepared['active_uv_names'][mi] not in available:
                        raise ValueError('active render UV map was excluded; export all UV maps or include it in UV roles')
                    colors = dict(zip(mesh.get('color_layer_names', []), mesh.get('color_layers', [])))
                    missing = set(plan.get('color_names', [])) - colors.keys()
                    if missing:
                        raise ValueError(f'required evaluated mesh color attributes missing/excluded: {sorted(missing)}; export all color layers')
                    obj = prepared['objects'][mi]
                    target_entry, geometry = entry, None
                    if mutate:
                        ids = np.concatenate([mesh['indices'][int(p[0]):int(p[0]+p[1])] for p in primitives[mask]]).astype(np.int64)
                        # The interchange arrays use reversed winding and flipped V.
                        # Restore Blender conventions for baking, then convert the
                        # destination atlas back below before the DAE writer uses it.
                        ids = ids.reshape(-1, 3)[:, ::-1].ravel()
                        source_uvs = []
                        for n, a in originals[mi]:
                            values = a[ids].copy(); values[:, 1] = 1 - values[:, 1]
                            source_uvs.append((n, values))
                        geometry = dict(vertices=mesh['vertices'][ids]/prepared['scale'],
                             normals=mesh['normals'][ids] if 'normals' in mesh else None,
                             uvs=source_uvs, active_uv=prepared['active_uv_names'][mi],
                             colors=[(n, colors[n][ids]) for n in plan.get('color_names', [])],
                             matrix=obj.matrix_world.copy(), object=obj.name, ids=ids, mesh=mesh)
                        target_entry = entry if jobs == 0 else dict(entry)
                        target_index = index if jobs == 0 else len(data['materials'])
                        if jobs: data['materials'].append(target_entry)
                        primitives[mask,2] = (flags[mask] & 0xf0000000) | target_index
                    plans.append((target_entry, material, plan, geometry, obj.name))
                    jobs += 1
        except ValueError as exc:
            failures.append(f'{entry["name"]}: {exc}')
    if failures:
        raise ValueError('Material Package cannot translate these materials:\n' + '\n'.join(failures))
    return plans


def validate_package(prepared, destination):
    """Material-aware, non-baking validation for the exact prepared export.

    This evaluates the same graph, image, UV, color-attribute, object-atlas and
    destination rules as ``stage_package``. It creates no files and does not
    mutate the prepared export or the source scene.
    """
    virtual, resolution, namespace, texture_folder = _validate_package_settings(prepared, destination)
    plans = _material_plans(prepared, mutate=False)
    object_jobs = sum(geometry is not None or object_name is not None for _, _, _, geometry, object_name in plans)
    warnings = sum(len(plan.get('warnings', [])) for _, _, plan, _, _ in plans)
    return dict(status='passed', materials=len(prepared['data']['materials']), materialJobs=len(plans),
                uvTileJobs=len(plans)-object_jobs, objectAtlasJobs=object_jobs, warnings=warnings,
                resolution=resolution, virtualDirectory=virtual, textureDirectory=str(texture_folder),
                namespace=namespace)


def stage_package(context, prepared, destination, stage_dir, report):
    """Return (temporary file, final file) pairs; no destination changed here."""
    opts, data = prepared['options'], prepared['data']
    virtual, resolution, namespace, texture_folder = _validate_package_settings(prepared, destination)
    plans = _material_plans(prepared, mutate=True)
    records, mappings, files, texture_paths = {}, [], [], {}
    def store_map(values, suffix, color=False):
        payload = png_bytes(values, color)
        digest = hashlib.sha256(payload).hexdigest()
        filename = digest[:24] + '.' + suffix + '.png'
        final = texture_folder / filename
        if filename not in texture_paths:
            if final.exists():
                if final.is_symlink() or hashlib.sha256(final.read_bytes()).hexdigest() != digest:
                    raise ValueError(f'Texture output conflict: {final}')
            else:
                temp = stage_dir / filename; temp.write_bytes(payload); files.append((temp, final))
            texture_paths[filename] = dict(file=str(final), sha256=digest)
        elif texture_paths[filename]['sha256'] != digest:
            raise ValueError('Texture filename digest collision; export cancelled')
        return virtual + '/' + texture_folder.name + '/' + filename
    for number, (entry, material, plan, geometry, object_name) in enumerate(plans, 1):
        report('INFO', f'Material {number}/{len(plans)}: {material.name}')
        source_label = material.name + ('__' + object_name if object_name else '')
        material_name = namespace + '_' + re.sub(r'[^A-Za-z0-9_]', '_', material.name)[:45] + '_' + hashlib.sha256(source_label.encode()).hexdigest()[:8]
        stage = dict(baseColorFactor=[1,1,1,1], roughnessFactor=1, metallicFactor=1)
        record = dict(name=material_name, mapTo=material_name, **{'class':'Material'}, version=1.5,
                      Stages=[stage, {}, {}, {}], dynamicCubemap=True, materialTag0='beamng', materialTag1='stadium',
                      doubleSided=not material.use_backface_culling)
        # Solid materials use tiny maps; connected graphs use the requested resolution.
        p = principled(material)
        size = resolution if p and any(p.inputs[n].is_linked for n in CHANNELS) else 32
        with baker(context, material, plan, size, geometry) as (sample, p, atlas):
            base, alpha = sample('Base Color'), sample('Alpha')[:, :, 0]
            if plan.get('glass'):
                transmission = np.clip(sample('Transmission Weight')[:,:,0],0,1)
                alpha *= 1 - transmission * (1 - float(opts.get('glass_opacity', .15)))
            base[:, :, 3] = 1  # BeamNG opacity is explicit, not accidentally multiplied twice.
            stage['baseColorMap'] = store_map(base, 'color', True)
            for name, key in [('Roughness', 'roughnessMap'), ('Metallic', 'metallicMap')]:
                if p.inputs[name].is_linked:
                    stage[key] = store_map(sample(name), 'data')
                else:
                    stage['roughnessFactor' if name == 'Roughness' else 'metallicFactor'] = float(p.inputs[name].default_value)
            coat = p.inputs.get('Coat Weight')
            coat_roughness = p.inputs.get('Coat Roughness')
            if coat and (coat.is_linked or float(coat.default_value) > 1e-6):
                if coat.is_linked:
                    stage['clearCoatMap'] = store_map(sample('Coat Weight'), 'data')
                    stage['clearCoatFactor'] = 1.
                else:
                    stage['clearCoatFactor'] = float(coat.default_value)
                if coat_roughness:
                    stage['clearCoatRoughnessFactor'] = float(coat_roughness.default_value)
            if p.inputs['Normal'].is_linked:
                stage['normalMap'] = store_map(sample('Normal'), 'normal')
            if np.any(alpha < .999):
                opacity = np.ones_like(base); opacity[:, :, :3] = alpha[:, :, None]
                stage['opacityMap'] = store_map(opacity, 'data')
                record.update(translucent=True, translucentBlendOp='PreMulAlpha', translucentRecvShadows=True)
                if opts.get('material_alpha', 'BLEND') == 'CLIP':
                    record.update(alphaTest=True, alphaRef=128)
            strength = sample('Emission Strength')[:, :, 0]
            if np.any(strength > 0):
                emission = sample('Emission Color'); emission[:, :, :3] *= strength[:, :, None]
                peak = max(float(np.max(emission[:, :, :3])), 1e-8)
                if peak > 1e-8:
                    emission[:, :, :3] /= peak
                    stage.update(emissiveMap=store_map(emission, 'color', True), emissiveFactor=[1,1,1],
                                 emissiveIntensityNits=peak * float(opts.get('emission_nits', 100)))
            if geometry is not None:
                mesh = geometry['mesh']
                if 'uv0' not in mesh:
                    mesh['uv0'] = np.zeros((len(mesh['vertices']),2),dtype=np.float32)
                    mesh['tvert_names'] = ['__BeamNG_BakedUV']
                atlas[:, 1] = 1 - atlas[:, 1]
                mesh['uv0'][geometry['ids']] = atlas
        records[material_name] = record
        mappings.append(dict(source=material.name, object=object_name, exported=material_name,
                             method='Object atlas bake' if geometry is not None else 'UV tile bake', resolution=size,
                             atlas=geometry.get('atlas_method') if geometry is not None else None, **plan))
        entry['name'] = material_name
    temp = stage_dir / 'materials.json'; temp.write_text(json.dumps(records, indent=2, allow_nan=False), encoding='utf8')
    files.append((temp, destination.with_suffix('.materials.json')))
    manifest = dict(schema='BeamNGMaterialPackageV1', sourceBlend=bpy.data.filepath, mesh=destination.name,
                    materialCount=len(records), textureCount=len(texture_paths), materials=mappings,
                    textures=list(texture_paths.values()), scope='Static Blender PBR appearance; no exact Frostbite/game-lighting claim',
                    note='PNG authoring textures. Let BeamNG cook them to DDS before mod distribution. Old content-addressed textures are retained on re-export.')
    temp = stage_dir / 'report.json'; temp.write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding='utf8')
    files.append((temp, destination.with_suffix('.material-report.json')))
    return files
