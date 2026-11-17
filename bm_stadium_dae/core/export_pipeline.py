# SPDX-License-Identifier: GPL-3.0-or-later
"""One serializer for file-menu exports and saved collection batches."""
from pathlib import Path
import json
import os
import uuid
import tempfile
import shutil
import bpy
import numpy as np

from .mesh_extractor import MeshExtractor
from .cache_io import write_cache
from .cache_layout import restore_layout
from .scene_io import bake_cache_transforms, write_dae, source_name, scene_unit_scale

DEFAULTS = dict(export_format='DAE', apply_modifiers=True, custom_normals=True, active_uv_only=False,
                active_color_only=False, global_scale=1., compress=True, preserve_cache_layout=True, preserve_edge_marks=True,
                material_package=False, game_directory='', material_resolution='1024', material_alpha='BLEND', emission_nits=100.,
                approximate_glass=False, glass_opacity=.15, approximate_sheen=True, bake_object_materials=True,
                static_stadium=False)


def atomic_sibling(path, suffix):
    """Return a short same-directory atomic filename safe on legacy Windows paths.

    Repeating the potentially long destination basename in a hidden UUID temp
    name can push an otherwise valid export past Windows' 260-character path
    limit. The UUID already supplies uniqueness, so keep atomic siblings short.
    """
    return path.with_name(f'.bm-{uuid.uuid4().hex[:16]}.{suffix}')


def options_from(settings):
    return {name: getattr(settings, name, value) for name, value in DEFAULTS.items()}


def export_path(filepath, export_format):
    if not filepath or not str(filepath).strip():
        raise ValueError('Choose an export file for the collection')
    if str(filepath).startswith('//') and not bpy.data.filepath:
        raise ValueError('Save the blend file before using a // relative export path')
    path = Path(bpy.path.abspath(str(filepath))).expanduser().resolve()
    path = path.with_suffix('.cdae' if export_format == 'CDAE' else '.dae')
    if not path.parent.is_dir() or path.is_dir():
        raise ValueError(f'Choose a file inside an existing folder: {path}')
    return path


def prepare_export(context, candidates, options=None, report=lambda level, message: None):
    opts = dict(DEFAULTS, **(options or {}))
    if opts['material_package'] and opts['export_format'] != 'DAE':
        raise ValueError('BeamNG Material Package requires DAE format; CDAE remains geometry-only')
    objects = sorted({o for o in candidates if o.type == 'MESH' and
                      (len(o.data.vertices) or (opts['apply_modifiers'] and len(o.modifiers)))}, key=lambda o: o.name)
    if not objects:
        raise ValueError('No non-empty mesh objects in the export scope')
    names = [source_name(o) for o in objects]
    if len(set(names)) != len(names) and not (opts['export_format'] == 'CDAE' and opts['preserve_cache_layout']):
        raise ValueError('Exported mesh names must be unique; select one copy or rename duplicated parts/LOD objects')
    context.view_layer.update()
    for obj in objects:
        if not np.isfinite(np.asarray(obj.matrix_world)).all():
            raise ValueError(f'{obj.name}: non-finite object transform')
        if opts['apply_modifiers'] and obj.name not in context.view_layer.objects:
            raise ValueError(f'{obj.name}: enable its collection in this view layer before evaluating modifiers')
    scale = float(opts['global_scale']) * scene_unit_scale(context)
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError('Export scale must be a positive finite number')
    extractor = MeshExtractor(global_scale=scale, apply_modifiers=opts['apply_modifiers'], custom_normals=opts['custom_normals'],
                         active_uv_only=opts['active_uv_only'], active_color_only=opts['active_color_only'],
                         preserve_edge_marks=opts['preserve_edge_marks'], report=report)
    data = extractor.extract(objects)
    if opts.get('static_stadium'):
        unexpected = [r['name'] for r in extractor.omitted_objects if not r['expected']]
        if unexpected:
            raise ValueError('Required stadium objects evaluated empty: ' + ', '.join(unexpected[:12]) +
                             '. Check Geometry Nodes, visibility masks and instance sources; no files replaced.')
    objects = extractor.exported_objects
    if not objects:
        raise ValueError('No evaluated faces or edges in the export scope; enable Apply Modifiers for Geometry Nodes')
    if any(m.get('is_null') and m.get('line_indices') is None for m in data['meshes']):
        raise ValueError('An evaluated object has neither faces nor loose edges; export cancelled')
    if not opts['custom_normals'] and any(m.get('editor_mesh') for m in data['meshes']):
        report('WARNING', 'Custom Normals is off; editing marks are saved, but BeamNG shading may differ')
    if any(any(c.isspace() for c in name) for name in names + [m['name'] for m in data['materials']]):
        report('WARNING', 'Names contain whitespace; BeamNG may shorten them. Use underscore names for game assets')
    if opts['export_format'] == 'CDAE':
        if any(m.get('is_null') for m in data['meshes']):
            raise ValueError('CDAE requires face geometry; use DAE for loose edges')
        if any(m.get('line_indices') is not None for m in data['meshes']):
            report('WARNING', 'CDAE contains faces only; loose edges are omitted. Use DAE to retain them')
        if any(len(m.get('tvert_names', [])) > 2 or len(m.get('color_layers', [])) > 1 for m in data['meshes']):
            raise ValueError('CDAE supports two UV maps and one color layer; assign UV roles, choose active-only layers or use DAE')
        if any(np.any((m['colors'] < 0) | (m['colors'] > 1)) for m in data['meshes'] if m.get('colors') is not None):
            report('WARNING', 'CDAE colors outside 0..1 are clamped to 8-bit RGBA; use DAE to keep float colors')
        bake_cache_transforms(data, objects, scale)
        if opts['preserve_cache_layout']:
            restore_layout(data, objects)
    return dict(data=data, objects=objects, scale=scale, options=opts, material_sources=extractor.material_sources,
                active_uv_names=extractor.active_uv_names, omitted_objects=extractor.omitted_objects)


def export_batch(context, requests, report=lambda level, message: None):
    """Serialize every request before replacing any destination; roll back failed commits."""
    jobs, seen = [], set()
    for filepath, objects, options in requests:
        opts = dict(DEFAULTS, **options)
        path = export_path(filepath, opts['export_format'])
        key = os.path.normcase(str(path))
        if key in seen:
            raise ValueError(f'Two collections have the same export destination: {path}')
        seen.add(key)
        jobs.append(dict(path=path, objects=list(objects), options=opts))
    if not jobs:
        raise ValueError('No collections are marked for BeamNG export')
    staged, commits, extra_dirs, new_dirs, outputs = [], [], [], [], []
    try:
        for job in jobs:
            path = job['path']
            prepared = prepare_export(context, job['objects'], job['options'], report)
            temp = atomic_sibling(path, 'tmp')
            staged.append(temp)
            if prepared['options']['material_package']:
                from .material_package import stage_package
                work = Path(tempfile.mkdtemp(prefix='.beamng-material-', dir=path.parent))
                extra_dirs.append(work)
                outputs.extend(stage_package(context, prepared, path, work, report))
            if prepared['options']['export_format'] == 'CDAE':
                write_cache(temp, prepared['data'], prepared['options']['compress'])
            else:
                profile = write_dae(temp, prepared['data'], prepared['objects'], prepared['scale'],
                                    static_stadium=prepared['options'].get('static_stadium',False))
                if profile is not None:
                    profile.update(exporterVersion='1.1.2', blender=bpy.app.version_string,
                                   omittedObjects=prepared['omitted_objects'])
                    staged_report = atomic_sibling(path,'tmp')
                    staged.append(staged_report)
                    staged_report.write_text(json.dumps(profile,indent=2),encoding='utf8')
                    outputs.append((staged_report,path.with_suffix('.export-report.json')))
                    audit = prepared['options'].get('visibility_audit')
                    if audit is not None:
                        audit = json.loads(json.dumps(audit))
                        exported = {o.name for o in prepared['objects']}
                        skipped = {r['name']:r for r in prepared['omitted_objects']}
                        for row in audit['objects']:
                            row['selectedForEvaluation'] = row['included']
                            row['exported'] = row['name'] in exported
                            row['included'] = row['exported']
                            if row['name'] in skipped: row['evaluation'] = skipped[row['name']]
                        audit['selectedMeshes'] = audit['exportedMeshes']
                        audit['exportedMeshes'] = len(exported)
                        audit['exporterVersion'] = '1.1.2'
                        audit['countsDescribe'] = 'selection reasons; exported is final geometry result'
                        staged_audit = atomic_sibling(path,'tmp');staged.append(staged_audit)
                        staged_audit.write_text(json.dumps(audit,indent=2),encoding='utf8')
                        outputs.append((staged_audit,path.with_suffix('.visibility.json')))
            outputs.append((temp, path))
        destinations = [os.path.normcase(str(path)) for temp, path in outputs]
        if len(destinations) != len(set(destinations)):
            raise ValueError('Export package destinations overlap')
        try:
            for temp, path in outputs:
                if not path.parent.exists():
                    path.parent.mkdir(); new_dirs.append(path.parent)
                if path.is_symlink() or path.is_dir():
                    raise ValueError(f'Export destination is not a regular file: {path}')
                record = dict(path=path, backup=None, written=False)
                commits.append(record)
                if path.exists():
                    backup = atomic_sibling(path, 'bak')
                    os.replace(path, backup); record['backup'] = backup
                os.replace(temp, path); record['written'] = True
        except Exception as original_error:
            errors = []
            for record in reversed(commits):
                try:
                    if record['written'] and record['path'].exists():
                        record['path'].unlink()
                    if record['backup']:
                        os.replace(record['backup'], record['path'])
                except OSError as exc:
                    errors.append(f'{record["backup"]}: {exc}')
            if errors:
                raise RuntimeError(f'Export failed ({original_error}); recover retained backups: ' + '; '.join(errors)) from original_error
            raise
        for record in commits:
            if record['backup']:
                try:
                    record['backup'].unlink()
                except OSError:
                    report('WARNING', f'Export saved; previous file remains at {record["backup"]}')
    finally:
        for temp in staged:
            if temp.exists():
                temp.unlink()
        for directory in extra_dirs:
            shutil.rmtree(directory)
        for directory in reversed(new_dirs):
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
    return [job['path'] for job in jobs]


def scene_collections(scene):
    seen, pending = set(), [scene.collection]
    while pending:
        col = pending.pop()
        if col in seen:
            continue
        seen.add(col); yield col
        pending.extend(reversed(list(col.children)))


def collection_objects(context, collection):
    if collection not in set(scene_collections(context.scene)):
        raise ValueError('The export collection does not belong to the current scene')
    settings = collection.beamng_export
    context.view_layer.update()
    candidates = collection.all_objects if settings.include_children else collection.objects
    scene_objects = set(context.scene.objects)
    return [obj for obj in candidates if obj in scene_objects and obj.type == 'MESH' and
            (settings.include_hidden or obj.visible_get(view_layer=context.view_layer))]


def current_collection(context):
    return context.scene.beamng_tools.collection or context.collection
