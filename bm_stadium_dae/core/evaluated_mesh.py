# SPDX-License-Identifier: GPL-3.0-or-later
"""Read evaluated geometry, realizing instances in a disposable export object."""
from contextlib import contextmanager
import bpy


@contextmanager
def export_mesh(obj, apply_modifiers=True):
    if not apply_modifiers:
        yield obj.data, obj
        return
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    # Disabled viewport objects can be absent from the dependency graph:
    # evaluated_get then returns the original ID, which rejects evaluated_geometry.
    # Reference it from the disposable helper to request genuine evaluation,
    # including modifiers, without changing any visibility flag on the source.
    needs_helper = not evaluated.is_evaluated
    if not needs_helper:
        geometry = evaluated.evaluated_geometry()
        points = geometry.instances_pointcloud()
        needs_helper = points is not None and len(points.points) > 0
    helper = base = group = None
    try:
        if needs_helper:
            # Object Info reads the original evaluated result. Copying its modifier
            # stack would change Self Object and other object-dependent inputs.
            base = bpy.data.meshes.new('__BeamNG_export_instances')
            helper = bpy.data.objects.new('__BeamNG_export_instances', base)
            group = bpy.data.node_groups.new('__BeamNG_export_realize', 'GeometryNodeTree')
            group.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
            info = group.nodes.new('GeometryNodeObjectInfo')
            info.transform_space = 'ORIGINAL'
            info.inputs['Object'].default_value = obj
            info.inputs['As Instance'].default_value = False
            realize = group.nodes.new('GeometryNodeRealizeInstances')
            output = group.nodes.new('NodeGroupOutput')
            group.links.new(info.outputs['Geometry'], realize.inputs['Geometry'])
            group.links.new(realize.outputs['Geometry'], output.inputs['Geometry'])
            helper.modifiers.new('Export instances', 'NODES').node_group = group
            helper.matrix_world = obj.matrix_world.copy()
            bpy.context.scene.collection.objects.link(helper)
            bpy.context.view_layer.update()
            depsgraph = bpy.context.evaluated_depsgraph_get()
            evaluated = helper.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
        try:
            yield mesh, evaluated
        finally:
            evaluated.to_mesh_clear()
    finally:
        if helper is not None:
            bpy.data.objects.remove(helper, do_unlink=True)
        if group is not None:
            bpy.data.node_groups.remove(group)
        if base is not None:
            bpy.data.meshes.remove(base)
