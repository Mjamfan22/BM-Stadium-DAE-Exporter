"""Conservative stadium scope. Never change source visibility."""
from collections import Counter

SOURCE_FLAGS = ('bm_instance_prototype', 'bm_original_seat_source', 'bm_crowd_source', 'bm_engine_light_blocker')

def source_only(obj):
    if bool(obj.get('bm_engine_light_blocker', False)):
        return True
    # Structure repair clones retain the prototype marker. A real placement ID
    # takes precedence over that inherited marker; lights remain excluded above.
    if obj.get('bm_scene_instance_id'):
        return False
    if any(bool(obj.get(k, False)) for k in SOURCE_FLAGS):
        return True
    return any(c.name in {'Original_FBX_Prototypes', 'Instance_Prototypes', 'Original_Seat_Source'} for c in obj.users_collection)

def classify(context, include_hidden_placements=True):
    enabled=set()
    restrictions=[]
    def walk(lc, blocked=False):
        blocked = blocked or lc.exclude or lc.hide_viewport or lc.collection.hide_viewport or lc.collection.hide_render
        if blocked:
            restrictions.append(lc.name)
        else:
            enabled.update(lc.collection.objects)
        for child in lc.children:
            walk(child,blocked)
    walk(context.view_layer.layer_collection)
    objects=[]; rows=[]
    for o in context.scene.objects:
        if o.type != 'MESH': continue
        placed=bool(o.get('bm_scene_instance_id'))
        visible=o.visible_get(view_layer=context.view_layer)
        eye=o.hide_get(view_layer=context.view_layer) if o.name in context.view_layer.objects else False
        if source_only(o): reason='source_or_engine_helper'
        elif o.hide_render: reason='render_disabled'
        elif o not in enabled: reason='collection_disabled'
        elif o.hide_viewport: reason='viewport_disabled'
        elif visible: reason='visible'
        elif eye and placed and include_hidden_placements: reason='included_hidden_placement'
        elif eye and placed: reason='hidden_placement'
        else: reason='hidden_unclassified'
        included=reason in {'visible','included_hidden_placement'}
        if included: objects.append(o)
        rows.append(dict(name=o.name,reason=reason,included=included,placed=placed,
                         sourceAsset=str(o.get('bm_source_asset','')),visible=visible,
                         eyeHidden=eye,viewportDisabled=o.hide_viewport,renderDisabled=o.hide_render))
    return objects, dict(counts=dict(Counter(r['reason'] for r in rows)),objects=rows,
                         restrictedCollections=sorted(set(restrictions)),exportedMeshes=len(objects))
