# SPDX-License-Identifier: GPL-3.0-or-later
"""Preserve static cache object/detail associations without retaining stale geometry."""
import json
import uuid

import numpy as np

from .scene_io import source_name


def remember_layout(data, mesh_objects):
    if 'version' not in data.get('cache_metadata', {}):
        return
    source_id = uuid.uuid4().hex
    details = data['cache_metadata'].get('details', [])
    for oi, entry in enumerate(data['objects']):
        slots = range(entry['num_meshes'])
        present = [s for s in slots if not data['meshes'][entry['start_mesh'] + s].get('is_null')]
        record = {'source_id': source_id, 'object_index': oi, 'name': data['names'][entry['name_index']],
                  'slot_count': entry['num_meshes'], 'present_slots': present,
                  'subshape': entry.get('subshape', 0), 'details': details}
        for slot in slots:
            obj = mesh_objects.get(entry['start_mesh'] + slot)
            if obj is not None:
                obj['beamng_cache_layout'] = json.dumps(record, ensure_ascii=False)
                obj['beamng_lod_slot'] = slot


def restore_layout(data, objects):
    """Group imported slots after transforms are baked; reject accidental omissions."""
    groups = {}
    for i, obj in enumerate(objects):
        record = json.loads(obj.get('beamng_cache_layout', '{}'))
        if record and source_name(obj) == record['name']:
            key = (record['source_id'], record['object_index'])
            subkey = (record['source_id'], int(record['subshape']))
            slot = int(obj.get('beamng_lod_slot', 0))
        else:
            key, subkey, slot = ('new', i), ('new', 0), 0
            record = {'name': source_name(obj), 'slot_count': 1, 'present_slots': [0],
                      'details': [{'name': 'detail2', 'subshape': 0, 'mesh_slot': 0, 'size': 2.}], 'subshape': 0}
        group = groups.setdefault(key, {'record': record, 'slots': {}, 'subkey': subkey})
        if slot in group['slots']:
            raise ValueError(f'Duplicate cache slot {slot} for {record["name"]}; select one copy or rename it')
        group['slots'][slot] = i
    names = [g['record']['name'] for g in groups.values()]
    if len(set(names)) != len(names):
        raise ValueError('Exported cache object names must be unique; rename duplicated parts')
    subkeys = list(dict.fromkeys(g['subkey'] for g in groups.values()))
    meshes, nodes, entries, names, details = [], [], [], [], []
    for subshape, subkey in enumerate(subkeys):
        subset = [g for g in groups.values() if g['subkey'] == subkey]
        record = subset[0]['record']
        source_details = [d for d in record['details'] if d['subshape'] == record['subshape']]
        if any(d['subshape'] < 0 for d in record['details']):
            raise ValueError('Billboard cache details cannot be rebuilt; disable Preserve Cache Layout for a static export')
        for d in source_details:
            details.append(dict(d, subshape=subshape))
        for group in subset:
            record, slots = group['record'], group['slots']
            if set(slots) != set(record['present_slots']):
                raise ValueError(f'Select every non-empty LOD/collision slot of {record["name"]}, or disable Preserve Cache Layout')
            count = int(record['slot_count'])
            if not 1 <= count <= 1024 or any(not 0 <= s < count for s in slots):
                raise ValueError('Invalid cache slot metadata')
            start = len(meshes)
            for slot in range(count):
                if slot not in slots:
                    meshes.append({'is_null': True, 'mesh_type': 4})
                    continue
                i = slots[slot]
                mesh = data['meshes'][i]
                mesh['vertices'] = np.asarray(mesh['vertices']) + np.asarray(data['nodes'][i]['translation'])
                meshes.append(mesh)
            ni = len(nodes)
            nodes.append({'name': record['name'], 'translation': [0., 0., 0.]})
            names.append(record['name'])
            entries.append({'name_index': ni, 'num_meshes': count, 'start_mesh': start,
                            'node_index': ni, 'subshape': subshape})
    if not details or not any(d['size'] >= 0 for d in details):
        raise ValueError('Cache layout has no visible detail; disable Preserve Cache Layout for a static export')
    data.update(meshes=meshes, nodes=nodes, objects=entries, names=names, details=details)
