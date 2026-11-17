# SPDX-License-Identifier: GPL-3.0-or-later
"""Export-only BeamNG static shape names; preserve source IDs and transforms."""
import hashlib
import re
import xml.etree.ElementTree as ET

NS = 'http://www.collada.org/2005/11/COLLADASchema'
def tag(name): return '{' + NS + '}' + name

def part_name(index, original):
    label = re.sub(r'[^A-Za-z0-9_]', '_', original)[:36]
    digest = hashlib.sha256(original.encode('utf8')).hexdigest()[:10]
    # Alphabetic a before the common LOD is required by BeamNG. The unique
    # part identity is BEFORE that suffix, so numeric source names aren't LODs.
    return f'stadium_{index:05d}_{label}_{digest}_a1'

def apply_static_profile(root):
    scenes = root.findall('./' + tag('library_visual_scenes') + '/' + tag('visual_scene'))
    if len(scenes) != 1:
        raise ValueError('Static stadium export requires exactly one visual scene')
    scene = scenes[0]
    nodes = list(scene.iter(tag('node')))
    geometries = {g.get('id'): g for g in root.findall('./' + tag('library_geometries') + '/' + tag('geometry'))}
    used = set(); rows = []; anchors = []
    for node in nodes:
        instances = node.findall(tag('instance_geometry'))
        original = node.get('name', node.get('id', ''))
        if not instances:
            node.set('name', 'stadium_anchor_' + str(len(anchors)) + '_node')
            anchors.append(dict(id=node.get('id'), source=original, exported=node.get('name')))
            continue
        if len(instances) != 1:
            raise ValueError('Static stadium node has multiple geometry instances')
        gid = instances[0].get('url', '').lstrip('#')
        if gid not in geometries or gid in used:
            raise ValueError('Missing or multiply instanced static stadium geometry: ' + gid)
        used.add(gid)
        name = part_name(len(rows), original)
        rows.append(dict(nodeId=node.get('id'), geometryId=gid, source=original,
                         sourceGeometry=geometries[gid].get('name'), exported=name))
        node.set('name', name)
        geometries[gid].set('name', name)
    if used != set(geometries):
        raise ValueError('Static stadium has unreferenced geometries')
    names = [r['exported'].casefold().removesuffix('1') for r in rows]
    if len(names) != len(set(names)):
        raise ValueError('Static stadium detail names collide')
    all_ids = {e.get('id') for e in root.iter() if e.get('id')}
    if all_ids & {'BMStadiumStaticBase', 'BMStadiumStaticStart'}:
        raise ValueError('Static stadium hierarchy already exists')
    children = list(scene)
    if any(c.tag != tag('node') for c in children):
        raise ValueError('Unexpected visual scene content in static stadium export')
    for child in children: scene.remove(child)
    base = ET.SubElement(scene, tag('node'), id='BMStadiumStaticBase', name='base00', type='NODE')
    start = ET.SubElement(base, tag('node'), id='BMStadiumStaticStart', name='start01', type='NODE')
    start.extend(children)
    return dict(schema='BeamNGStadiumStaticShapeV1', visualParts=len(rows), detailSize=1,
                sourceNamesUnchanged=True, transformsUnchanged=True, meshArraysUnchanged=True,
                geometryNames=rows, anchors=anchors)
