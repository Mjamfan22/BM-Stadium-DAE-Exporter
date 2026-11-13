# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicit UV export roles and reversible, object-local livery previews."""
import bpy

_viewport_states = {}


def export_uv_layers(mesh, obj, active_only=False):
    settings = getattr(obj, 'beamng_mesh', None)
    if settings and settings.use_uv_roles:
        if active_only:
            raise ValueError(f'{obj.name}: disable Active UV Only when using assigned texture/livery UVs')
        if not settings.texture_uv:
            raise ValueError(f'{obj.name}: choose a texture UV map for UV0')
        names = [settings.texture_uv] + ([settings.livery_uv] if settings.livery_uv else [])
        if len(names) != len(set(names)):
            raise ValueError(f'{obj.name}: texture and livery must use different UV maps')
        if settings.require_livery and not settings.livery_uv:
            raise ValueError(f'{obj.name}: choose a livery UV map for UV1')
        for name in names:
            if name not in mesh.uv_layers:
                raise ValueError(f'{obj.name}: assigned UV map "{name}" is missing')
        layers = [mesh.uv_layers[name] for name in names]
        if settings.include_other_uvs:
            layers.extend(layer for layer in mesh.uv_layers if layer.name not in names)
        return layers
    if settings and settings.require_livery and len(mesh.uv_layers) < 2:
        raise ValueError(f'{obj.name}: a second UV map is required for the livery')
    return [mesh.uv_layers.active] if active_only and mesh.uv_layers.active else ([] if active_only else list(mesh.uv_layers))


def original_material(material):
    if material and material.get('beamng_uv_preview', False):
        return material.get('beamng_original_material')
    return material


def restore_preview(objects):
    removed = []
    for obj in objects:
        records = getattr(obj, 'beamng_preview_slots', ())
        for record in records:
            if record.index < len(obj.material_slots):
                slot = obj.material_slots[record.index]
                # Preserve an intentional material replacement made during preview.
                if slot.link == 'OBJECT' and slot.material == record.preview:
                    slot.link = record.link
                    if record.link == 'OBJECT':
                        slot.material = record.material
            if record.preview:
                removed.append(record.preview)
        if records:
            records.clear()
    for mat in set(removed):
        if mat.users == 0:
            bpy.data.materials.remove(mat)
    if not any(getattr(o, 'beamng_preview_slots', ()) for o in bpy.data.objects):
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                previous = _viewport_states.pop(area.as_pointer(), None)
                if previous and area.type == 'VIEW_3D' and area.spaces.active.shading.type == 'MATERIAL':
                    area.spaces.active.shading.type = previous


def _checker_image():
    image = next((i for i in bpy.data.images if i.get('beamng_uv_checker')), None)
    if image is None:
        image = bpy.data.images.new('BeamNG Livery UV Checker', width=1024, height=1024)
        image.generated_type = 'COLOR_GRID'
        image['beamng_uv_checker'] = True
    return image


def preview_livery(context, objects, mode='CHECKER', image=None):
    objects = list(objects)
    if not objects:
        raise ValueError('Select at least one mesh object')
    if mode == 'SKIN' and (image is None or image.type not in {'IMAGE', 'UV_TEST'}):
        raise ValueError('Choose a still skin image before previewing')
    prepared = []
    for obj in objects:
        if not obj.is_editable:
            raise ValueError(f'{obj.name}: create a local editable object before previewing')
        if obj.type != 'MESH' or not obj.material_slots:
            raise ValueError(f'{obj.name}: assign a material before previewing')
        settings = getattr(obj, 'beamng_mesh', None)
        if settings and settings.use_uv_roles and not settings.livery_uv:
            raise ValueError(f'{obj.name}: choose a Livery UV → UV1 map before previewing')
        layers = export_uv_layers(obj.data, obj)
        if len(layers) < 2:
            raise ValueError(f'{obj.name}: assign a livery map to UV1 before previewing')
        prepared.append((obj, layers[0].name, layers[1].name))
    restore_preview(objects)
    image = _checker_image() if mode == 'CHECKER' else image
    try:
        for obj, texture_uv, livery_uv in prepared:
            for index, slot in enumerate(obj.material_slots):
                source = original_material(slot.material)
                mat = source.copy() if source else bpy.data.materials.new('BeamNG UV Preview')
                mat.name = 'BeamNG Preview · ' + (source.name if source else obj.name)
                mat['beamng_uv_preview'] = True
                if source:
                    mat['beamng_original_material'] = source
                record = obj.beamng_preview_slots.add()
                record.index, record.link, record.material, record.preview = index, slot.link, source, mat
                mat.use_nodes = True
                nodes, links = mat.node_tree.nodes, mat.node_tree.links
                if mode == 'CHECKER':
                    nodes.clear()
                    output = nodes.new('ShaderNodeOutputMaterial'); output.location = (550, 0)
                    bsdf = nodes.new('ShaderNodeBsdfPrincipled'); bsdf.location = (250, 0)
                    bsdf.inputs['Roughness'].default_value = .7
                    links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
                else:
                    bsdf = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)
                    if bsdf is None:
                        raise ValueError(f'{obj.name}: skin preview requires a Principled material; use the UV Checker instead')
                    uv0 = nodes.new('ShaderNodeUVMap'); uv0.uv_map = texture_uv; uv0.location = (-1100, 150)
                    for node in list(nodes):
                        if node.type == 'TEX_IMAGE' and not node.inputs['Vector'].is_linked:
                            links.new(uv0.outputs['UV'], node.inputs['Vector'])
                        elif node.type == 'NORMAL_MAP' and not node.uv_map:
                            node.uv_map = texture_uv
                uv = nodes.new('ShaderNodeUVMap'); uv.uv_map = livery_uv; uv.location = (-850, -350)
                tex = nodes.new('ShaderNodeTexImage'); tex.image = image; tex.location = (-600, -350)
                links.new(uv.outputs['UV'], tex.inputs['Vector'])
                if mode == 'SKIN':
                    mix = nodes.new('ShaderNodeMixRGB'); mix.location = (-150, -200)
                    base = bsdf.inputs['Base Color']
                    if base.is_linked:
                        links.new(base.links[0].from_socket, mix.inputs[1])
                    else:
                        mix.inputs[1].default_value = base.default_value[:]
                    links.new(tex.outputs['Alpha'], mix.inputs[0])
                    links.new(tex.outputs['Color'], mix.inputs[2])
                    links.new(mix.outputs[0], base)
                else:
                    links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
                slot.link = 'OBJECT'; slot.material = mat
    except Exception:
        restore_preview(objects)
        raise
    if context.screen:
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                _viewport_states.setdefault(area.as_pointer(), area.spaces.active.shading.type)
                area.spaces.active.shading.type = 'MATERIAL'
    return len(objects)
