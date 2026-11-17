# SPDX-License-Identifier: GPL-3.0-or-later
"""Standalone static stadium DAE + BeamNG material package exporter."""
bl_info = {'name':'BM Stadium DAE Exporter', 'author':'BM; export engine adapted from Blenux',
           'version':(1,1,2), 'blender':(5,2,0), 'category':'Import-Export',
           'location':'File > Export > BeamNG Stadium (.dae)',
           'description':'Export stadium geometry, evaluated seats, textures and BeamNG materials'}
import json
import traceback
from pathlib import Path
import bpy
from bpy.props import BoolProperty, StringProperty, EnumProperty, FloatProperty
from bpy_extras.io_utils import ExportHelper
from .visibility_v2 import classify
from .core.export_pipeline import export_batch, export_path, options_from, prepare_export
from .core.material_package import validate_package

SETTING_NAMES=('include_hidden_placements','material_resolution','material_alpha','game_directory','global_scale','approximate_glass','approximate_sheen')

def draw_settings(layout,operator):
    layout.label(text='DAE + textures + BeamNG materials',icon='MESH_DATA')
    for name in SETTING_NAMES: layout.prop(operator,name)
    if operator.approximate_glass:
        layout.prop(operator,'glass_opacity')
        layout.label(text='Glass uses opacity; refraction is not preserved.',icon='INFO')
    layout.prop(operator,'emission_nits')

def stadium_options(operator):
    opts=options_from(operator)
    opts.update(export_format='DAE',material_package=True,apply_modifiers=True,
                active_uv_only=False,bake_object_materials=True,static_stadium=True)
    return opts

def record_error(context,operator,exc):
    payload=dict(exporter='BM Stadium DAE Exporter',version=list(bl_info['version']),
                 blender=bpy.app.version_string,operation=operator.bl_idname,
                 sourceBlend=bpy.data.filepath,destination=operator.filepath,
                 options=stadium_options(operator),error=str(exc),traceback=traceback.format_exc())
    context.window_manager.bm_stadium_last_error=json.dumps(payload,indent=2)
    print('BM_STADIUM_ERROR='+context.window_manager.bm_stadium_last_error)

class BM_OT_copy_error(bpy.types.Operator):
    bl_idname='bm_stadium.copy_last_error'
    bl_label='Copy Last Error'
    bl_description='Copy the complete error, exporter version and settings for troubleshooting'
    @classmethod
    def poll(cls,context): return bool(context.window_manager.bm_stadium_last_error)
    def execute(self,context):
        context.window_manager.clipboard=context.window_manager.bm_stadium_last_error
        self.report({'INFO'},'Copied the complete stadium export error')
        return {'FINISHED'}

class BM_OT_stadium_visibility(bpy.types.Operator):
    bl_idname='bm_stadium.check_visibility'
    bl_label='Check Stadium Visibility'
    bl_description='Report placed meshes and excluded sources without changing the scene'
    def execute(self,context):
        _,data=classify(context)
        text=bpy.data.texts.get('Stadium Export Visibility') or bpy.data.texts.new('Stadium Export Visibility')
        text.clear();text.write(json.dumps(data,indent=2))
        c=data['counts']; hidden=c.get('included_hidden_placement',0)
        blocked=sum(1 for r in data['objects'] if r['placed'] and r['reason'] in {'viewport_disabled','collection_disabled','render_disabled'})
        self.report({'INFO'},f"{data['exportedMeshes']} meshes; {hidden} hidden placements included; {blocked} disabled placements to review. See Text Editor: Stadium Export Visibility")
        return {'FINISHED'}

class BM_OT_export_stadium(bpy.types.Operator,ExportHelper):
    bl_idname='export_scene.bm_stadium_dae'
    bl_label='Export BeamNG Stadium'
    bl_options={'REGISTER'}
    filename_ext='.dae'
    filter_glob:StringProperty(default='*.dae',options={'HIDDEN'})
    include_hidden_placements:BoolProperty(name='Include Eye-hidden Placed Geometry',default=True,
        description='Include tagged world placements hidden with H/eye. Sources, light blockers and disabled collections stay excluded')
    material_resolution:EnumProperty(name='Texture Resolution',items=[(str(n),str(n),'Pixels per baked texture') for n in (512,1024,2048,4096)],default='2048')
    material_alpha:EnumProperty(name='Transparency',items=[('BLEND','Blended','Smooth transparency'),('CLIP','Cutout','Alpha test')],default='BLEND')
    game_directory:StringProperty(name='Game Texture Directory',description='Leave blank to infer /levels/... from the output folder',default='')
    approximate_glass:BoolProperty(name='Approximate Glass',default=True,description='Use opacity instead of refraction; an explicit visual approximation')
    approximate_sheen:BoolProperty(name='Approximate Sheen',default=True,description='Keep base PBR for cloth materials and record that BeamNG has no separate sheen lobe')
    glass_opacity:FloatProperty(name='Glass Opacity',default=.15,min=0,max=1)
    emission_nits:FloatProperty(name='Nits per Emission Strength',default=100,min=.01,max=100000)
    global_scale:FloatProperty(name='Scale',default=1,min=.000001,max=1000000)
    @classmethod
    def poll(cls,context): return context.mode=='OBJECT'
    def invoke(self,context,event):
        if not self.filepath:
            self.filepath=context.scene.bm_stadium_last_export or (Path(bpy.data.filepath).stem+'.dae' if bpy.data.filepath else 'Stadium.dae')
        return ExportHelper.invoke(self,context,event)
    def draw(self,context):
        draw_settings(self.layout,self)
    def execute(self,context):
        context.window_manager.bm_stadium_last_error=''
        try:
            objects,audit=classify(context,self.include_hidden_placements)
            blocked=[r for r in audit['objects'] if r['placed'] and r['reason'] in {'viewport_disabled','collection_disabled','render_disabled'}]
            if blocked:
                self.report({'WARNING'},f'{len(blocked)} disabled placed meshes excluded; inspect the visibility report')
            opts=stadium_options(self);opts['visibility_audit']=audit
            paths=export_batch(context,[(self.filepath,objects,opts)],lambda level,msg:self.report({level},msg))
            context.scene.bm_stadium_last_export=str(paths[0])
            result=json.loads(paths[0].with_suffix('.export-report.json').read_text(encoding='utf8'))
            self.report({'INFO'},f"Exported {result['visualParts']} stadium meshes with materials: {paths[0].name}")
            return {'FINISHED'}
        except Exception as exc:
            record_error(context,self,exc)
            self.report({'ERROR'},f'Stadium export failed: {exc}')
            return {'CANCELLED'}

class BM_OT_validate_stadium(bpy.types.Operator,ExportHelper):
    bl_idname='bm_stadium.validate_full_export'
    bl_label='Validate Full Stadium Export'
    bl_description='Evaluate geometry, modifiers, instances, material graphs, images and UV/color requirements without writing export files'
    filename_ext='.dae'
    filter_glob:StringProperty(default='*.dae',options={'HIDDEN'})
    include_hidden_placements:BoolProperty(name='Include Eye-hidden Placed Geometry',default=True,
        description='Include tagged world placements hidden with H/eye. Sources, light blockers and disabled collections stay excluded')
    material_resolution:EnumProperty(name='Texture Resolution',items=[(str(n),str(n),'Pixels per baked texture') for n in (512,1024,2048,4096)],default='2048')
    material_alpha:EnumProperty(name='Transparency',items=[('BLEND','Blended','Smooth transparency'),('CLIP','Cutout','Alpha test')],default='BLEND')
    game_directory:StringProperty(name='Game Texture Directory',description='Leave blank to infer /levels/... from the proposed output folder',default='')
    approximate_glass:BoolProperty(name='Approximate Glass',default=True,description='Use opacity instead of refraction; an explicit visual approximation')
    approximate_sheen:BoolProperty(name='Approximate Sheen',default=True,description='Keep base PBR for cloth materials and record that BeamNG has no separate sheen lobe')
    glass_opacity:FloatProperty(name='Glass Opacity',default=.15,min=0,max=1)
    emission_nits:FloatProperty(name='Nits per Emission Strength',default=100,min=.01,max=100000)
    global_scale:FloatProperty(name='Scale',default=1,min=.000001,max=1000000)
    @classmethod
    def poll(cls,context): return context.mode=='OBJECT'
    def invoke(self,context,event):
        if not self.filepath:
            self.filepath=context.scene.bm_stadium_last_export or (Path(bpy.data.filepath).stem+'.dae' if bpy.data.filepath else 'Stadium.dae')
        return ExportHelper.invoke(self,context,event)
    def draw(self,context): draw_settings(self.layout,self)
    def execute(self,context):
        context.window_manager.bm_stadium_last_error=''
        try:
            objects,audit=classify(context,self.include_hidden_placements)
            blocked=[r for r in audit['objects'] if r['placed'] and r['reason'] in {'viewport_disabled','collection_disabled','render_disabled'}]
            if blocked:
                self.report({'WARNING'},f'{len(blocked)} disabled placed meshes excluded; inspect Stadium Visibility before export')
            opts=stadium_options(self)
            path=export_path(self.filepath,opts['export_format'])
            prepared=prepare_export(context,objects,opts,lambda level,msg:self.report({level},msg))
            summary=validate_package(prepared,path)
            summary.update(exporterVersion=list(bl_info['version']),blender=bpy.app.version_string,
                           proposedOutput=str(path),classifiedMeshes=len(objects),preparedMeshes=len(prepared['data']['meshes']),
                           omittedObjects=prepared['omitted_objects'])
            print('BM_STADIUM_PREFLIGHT='+json.dumps(summary,sort_keys=True))
            self.report({'INFO'},f"Preflight passed: {summary['preparedMeshes']} meshes, {summary['materials']} materials, {summary['materialJobs']} material jobs; no files written")
            return {'FINISHED'}
        except Exception as exc:
            record_error(context,self,exc)
            self.report({'ERROR'},f'Stadium preflight failed: {exc}')
            return {'CANCELLED'}

class BM_PT_stadium(bpy.types.Panel):
    bl_label='Stadium Export'
    bl_idname='BM_PT_stadium_export'
    bl_space_type='VIEW_3D';bl_region_type='UI';bl_category='Stadium'
    def draw(self,context):
        self.layout.operator('bm_stadium.check_visibility',icon='HIDE_OFF')
        self.layout.operator('bm_stadium.validate_full_export',text='Validate Full Export...',icon='CHECKMARK')
        self.layout.operator('export_scene.bm_stadium_dae',text='Export Stadium...',icon='EXPORT')
        self.layout.operator('bm_stadium.copy_last_error',icon='COPYDOWN')

def menu_export(self,context):
    self.layout.operator(BM_OT_export_stadium.bl_idname,text='BeamNG Stadium (.dae)')
CLASSES=(BM_OT_stadium_visibility,BM_OT_validate_stadium,BM_OT_export_stadium,BM_OT_copy_error,BM_PT_stadium)
def register():
    for cls in CLASSES:bpy.utils.register_class(cls)
    bpy.types.Scene.bm_stadium_last_export=StringProperty(subtype='FILE_PATH')
    bpy.types.WindowManager.bm_stadium_last_error=StringProperty(options={'SKIP_SAVE'})
    bpy.types.TOPBAR_MT_file_export.append(menu_export)
def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(menu_export)
    del bpy.types.Scene.bm_stadium_last_export
    del bpy.types.WindowManager.bm_stadium_last_error
    for cls in reversed(CLASSES):bpy.utils.unregister_class(cls)
