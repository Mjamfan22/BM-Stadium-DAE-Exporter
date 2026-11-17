"""Distinguish intentionally masked seat points from lost evaluated geometry."""
def expected_empty_seats(obj):
    if not obj.get('bm_seat_point_cloud') or len(obj.modifiers) != 1:
        return None
    attr = obj.data.attributes.get('bm_original_seat_visible')
    if attr is None or attr.domain != 'POINT' or attr.data_type != 'BOOLEAN':
        return None
    if not len(attr.data) or len(attr.data) != len(obj.data.vertices) or any(x.value for x in attr.data):
        return None
    mod = obj.modifiers[0]
    if mod.type != 'NODES' or not mod.show_viewport or not mod.node_group:
        return None
    outputs = [n for n in mod.node_group.nodes if n.type == 'GROUP_OUTPUT' and n.is_active_output]
    if len(outputs) != 1:
        return None
    links = list(outputs[0].inputs[0].links)
    if len(links) != 1 or links[0].from_node.bl_idname != 'GeometryNodeInstanceOnPoints':
        return None
    instance = links[0].from_node
    selection = list(instance.inputs['Selection'].links)
    if len(selection) != 1:
        return None
    node = selection[0].from_node
    if node.bl_idname != 'GeometryNodeInputNamedAttribute' or node.data_type != 'BOOLEAN' or node.mute:
        return None
    if node.inputs['Name'].is_linked or node.inputs['Name'].default_value != attr.name:
        return None
    return dict(reason='all_seats_masked_by_source', points=len(attr.data), visiblePoints=0,
                attribute=attr.name, fabricatedGeometry=False)
