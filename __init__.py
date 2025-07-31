bl_info = {
    "name": "Vertex Group Assistant",
    "description": "Transfer vertex groups and armatures from active to selected.",
    "author": "Marek Hanzelka",
    "version": (1, 0, 1),
    "blender": (4, 0, 0),
    "location": "Object > Vertex Groups",
    "warning": "",
    "wiki_url": "https://example.com/wiki/vertex_group_transfer",
    "tracker_url": "",
    "category": "Object"
}

import bpy

# Utility Functions
def validate_active_object(context, required_type='MESH', require_vertex_groups=False):
    obj = context.object
    if not obj:
        return "No active object!"
    if obj.type != required_type:
        return f"Active object must be a {required_type}!"
    if require_vertex_groups and not obj.vertex_groups:
        return "Active object must have vertex groups!"
    return None

def validate_selection(context, min_objects=2, require_active_in_selection=True, max_objects=None):
    selected_objects = context.selected_objects
    if len(selected_objects) < min_objects:
        return f"You must select at least {min_objects} objects."
    
    if max_objects is not None and len(selected_objects) > max_objects:
        return f"You can select a maximum of {max_objects} objects."

    if require_active_in_selection:
        active_object = context.active_object
        if active_object is None or active_object not in selected_objects:
            return "Active object must be among the selected objects."
    return None

def validate_armature_modifier(obj, require_armature=None):
    armature_modifiers = [mod for mod in obj.modifiers if mod.type == 'ARMATURE']
    if len(armature_modifiers) != 1:
        return "Object must have exactly one armature modifier."
    if armature_modifiers[0].object is None:
        return "Armature modifier has no object assigned."
    if require_armature and armature_modifiers[0].object != require_armature:
        return "Armature modifier does not point to the required armature."
    return None



def validate_armature_parent_and_modifier(obj):
    parent = obj.parent
    if not parent or parent.type != 'ARMATURE':
        return "Object must be parented to an armature."
    message = validate_armature_modifier(obj, require_armature=parent)
    if message:
        return message
    return None

def ensure_single_armature_modifier(obj, armature):
    armature_modifiers = [mod for mod in obj.modifiers if mod.type == 'ARMATURE']
    if len(armature_modifiers) == 0:
        new_modifier = obj.modifiers.new(name="Armature", type='ARMATURE')
        new_modifier.object = armature
        print(f"Created a new armature modifier for '{obj.name}'.")
        return True
    elif len(armature_modifiers) == 1:
        armature_modifiers[0].object = armature
        print(f"Updated existing armature modifier for '{obj.name}'.")
        return True
    else:
        return False

def get_used_vertex_groups(obj):
    weighted_groups = set()
    for vertex in obj.data.vertices:
        for vg in vertex.groups:
            if vg.weight > 0:
                weighted_groups.add(vg.group)
    return weighted_groups

def delete_zero_weight_vertex_groups(obj):
    weighted_groups = get_used_vertex_groups(obj)
    vertex_groups_to_remove = [
        vg.index for vg in obj.vertex_groups if vg.index not in weighted_groups
    ]
    removed_groups = []
    for index in sorted(vertex_groups_to_remove, reverse=True):
        removed_groups.append(obj.vertex_groups[index].name)
        obj.vertex_groups.remove(obj.vertex_groups[index])
    return removed_groups

def add_parent_bones(armature, used_bone_names):
    bpy.ops.object.mode_set(mode='EDIT')
    existing_bone_names = set(used_bone_names)
    for bone in armature.data.edit_bones:
        if bone.name in existing_bone_names:
            while bone:
                used_bone_names.add(bone.name)
                bone = bone.parent
    bpy.ops.object.mode_set(mode='OBJECT')

def delete_unused_bones(armature, used_bone_names):
    bpy.ops.object.mode_set(mode='EDIT')
    bones_to_delete = []
    for bone in armature.data.edit_bones:
        if bone.name not in used_bone_names:
            bones_to_delete.append(bone.name)
    num_bones_deleted = len(bones_to_delete)
    for bone_name in bones_to_delete:
        bone = armature.data.edit_bones.get(bone_name)
        if bone:
            armature.data.edit_bones.remove(bone)
    bpy.ops.object.mode_set(mode='OBJECT')
    return num_bones_deleted

def valid_interaction_mode():
    current_mode = bpy.context.mode
    if current_mode != 'OBJECT':
        return f"This function only works in object mode! Current mode is: '{current_mode}' "
    else:
        return None
# Operator Classes
class OBJECT_OT_transfer_vertex_groups_from_active(bpy.types.Operator):
    bl_idname = "object.transfer_vertex_groups_from_active"
    bl_label = "Transfer Vertex Groups from Active Object"
    bl_description = "Transfer vertex groups and armatures from active object to selected object(s)"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        message = validate_selection(context, min_objects=2)
        if message:
            cls.poll_message_set(message)
            return False
        message = validate_active_object(context, required_type='MESH', require_vertex_groups=True)
        if message:
            cls.poll_message_set(message)
            return False
        active_object = context.active_object
        message = validate_armature_parent_and_modifier(active_object)
        if message:
            cls.poll_message_set(message)
            return False
        
        message = valid_interaction_mode()
        if message:
            cls.poll_message_set(message)
            return False
        
        return True

    def execute(self, context):
        active_object = context.active_object
        # Get the armature that the active obj uses so the targets can be paranted to it
        active_object_arm_mod = next(m for m in active_object.modifiers if m.type == 'ARMATURE')
        if active_object_arm_mod and active_object_arm_mod.object:
            active_object_armature = active_object_arm_mod.object

        selected_objects = context.selected_objects
        targets = [obj for obj in selected_objects if obj != active_object and obj.type == 'MESH']

        for target in targets:
            # Ensure single armature modifier on each target
            success = ensure_single_armature_modifier(target, active_object.parent)
            if not success:
                self.report({'ERROR'}, f"'{target.name}' has multiple armature modifiers. Only one is allowed.")
                return {'CANCELLED'}

            # Set parent for each target 
            target.parent = active_object_armature
            target.matrix_parent_inverse = active_object.parent.matrix_world.inverted()

            # Transfer vertex groups to each target
            bpy.ops.object.select_all(action='DESELECT')
            active_object.select_set(True)
            target.select_set(True)
            context.view_layer.objects.active = active_object

            bpy.ops.object.data_transfer(
                data_type='VGROUP_WEIGHTS',
                use_auto_transform=False,
                use_object_transform=True,
                layers_select_src='ALL',
                layers_select_dst='NAME'
            )
        
        self.report({'INFO'}, f"Vertex groups transferred from '{active_object.name}' to {len(targets)} objects")
        
        # Deselect all to avoid wierd selection state from previsouse operations
        bpy.ops.object.select_all(action='DESELECT')

        # Reselect the objects in the list
        for obj in targets:
            obj.select_set(True)

        return {'FINISHED'}

class OBJECT_OT_delete_unused_vertex_groups(bpy.types.Operator):
    bl_idname = "object.delete_unused_vertex_groups"
    bl_label = "Delete Unused Vertex Groups"
    bl_description = "Remove all vertex groups from the active object that have no weight assignments"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        message = validate_active_object(context, required_type='MESH', require_vertex_groups=True)
        if message:
            cls.poll_message_set(message)
            return False
        active_object = context.active_object
        message = validate_armature_modifier(active_object)
        if message:
            cls.poll_message_set(message)
            return False
        
        message = valid_interaction_mode()
        if message:
            cls.poll_message_set(message)
            return False

        return True

    def execute(self, context):
        # Filter to only mesh objects
        current_selection = [obj for obj in bpy.context.selected_objects if obj.type == 'MESH']
        removed_groups = []

        # Process each mesh object
        for obj in current_selection:
            removed_groups += delete_zero_weight_vertex_groups(obj)

        # Gather reporting info
        num_removed_groups = len(removed_groups)
        num_selected_obj = len(current_selection)

        # Provide user feedback
        if removed_groups:
            if num_selected_obj == 1:
                self.report({'INFO'}, f"Removed {num_removed_groups} zero-weight vertex groups from {current_selection[0].name}!")
            else:
                self.report({'INFO'}, f"Removed {num_removed_groups} zero-weight vertex groups from {num_selected_obj} objects!")
        else:
            self.report({'INFO'}, "No zero-weight vertex groups found.")

        return {'FINISHED'}

class OBJECT_OT_confirm_delete_unused_bones(bpy.types.Operator):
    bl_idname = "object.confirm_delete_unused_bones"
    bl_label = "Delete Unused Bones"
    bl_description = "Delete all bones that do not have a corresponding vertex group"
    bl_options = {'REGISTER', 'UNDO'}
    
    duplicate_armature: bpy.props.BoolProperty(
        name="Duplicate Armature",
        description="Duplicate the armature before deleting bones",
        default=True
    )

    delete_empty_parent_bones: bpy.props.BoolProperty(
        name="Delete Empty Parent Bones",
        description="Delete parent bones that do not have a corresponding vertex group even if they have children that will not be deleted",
        default=False
    )

    @classmethod
    def poll(cls, context):
        message = validate_selection(context, min_objects=1,require_active_in_selection=True,max_objects=1)
        if message:
            cls.poll_message_set(message)
            return False

        message = validate_active_object(context, required_type='MESH', require_vertex_groups=True)
        if message:
            cls.poll_message_set(message)
            return False
        active_object = context.active_object
        message = validate_armature_parent_and_modifier(active_object)
        if message:
            cls.poll_message_set(message)
            return False
        
        message = valid_interaction_mode()
        if message:
            cls.poll_message_set(message)
            return False
        
        return True

    def invoke(self, context, event):
        if not self.poll(context):
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.label(
            text=f"You are about to delete unused bones from '{context.active_object.parent.name}'"
        )
        layout.prop(self, "duplicate_armature")
        layout.prop(self, "delete_empty_parent_bones")

    def execute(self, context):
        obj = context.active_object
        armature = obj.parent

        message = validate_armature_modifier(obj, require_armature=armature)
        if message:
            self.report({'ERROR'}, message)
            return {'CANCELLED'}

        armature.hide_viewport = False
        armature.hide_set(False)

        if self.duplicate_armature:
            bpy.ops.object.select_all(action='DESELECT')
            armature.select_set(True)
            context.view_layer.objects.active = armature
            bpy.ops.object.duplicate()
            duplicated_armature = context.active_object
            duplicated_armature.parent = None

            obj.parent = duplicated_armature

            for mod in obj.modifiers:
                if mod.type == 'ARMATURE':
                    mod.object = duplicated_armature

            armature = duplicated_armature

        used_bone_names = set([vg.name for vg in obj.vertex_groups])

        bpy.ops.object.select_all(action='DESELECT')
        armature.select_set(True)
        context.view_layer.objects.active = armature

        if not self.delete_empty_parent_bones:
            add_parent_bones(armature, used_bone_names)

        num_bones_deleted = delete_unused_bones(armature, used_bone_names)

        self.report({'INFO'}, f"Deleted {num_bones_deleted} unused bones.")

        return {'FINISHED'}

# Menu Class and Drawing Functions
class OBJECT_MT_vertex_tools(bpy.types.Menu):
    bl_label = "Vertex Group Assistant"
    bl_idname = "OBJECT_MT_vertex_tools"

    def draw(self, context):
        layout = self.layout
        layout.operator(
            OBJECT_OT_transfer_vertex_groups_from_active.bl_idname,
            icon='DECORATE_OVERRIDE'
        )
        layout.operator(
            OBJECT_OT_delete_unused_vertex_groups.bl_idname,
            icon='TRASH'
        )
        layout.operator(
            OBJECT_OT_confirm_delete_unused_bones.bl_idname,
            icon='BONE_DATA'
        )

def draw_vertex_group_menu(self, context):
    layout = self.layout
    layout.separator()
    layout.menu(OBJECT_MT_vertex_tools.bl_idname, icon='MODIFIER')

# Registration
def register():
    bpy.utils.register_class(OBJECT_OT_transfer_vertex_groups_from_active)
    bpy.utils.register_class(OBJECT_OT_delete_unused_vertex_groups)
    bpy.utils.register_class(OBJECT_OT_confirm_delete_unused_bones)
    bpy.utils.register_class(OBJECT_MT_vertex_tools)
    bpy.types.MESH_MT_vertex_group_context_menu.append(draw_vertex_group_menu)

def unregister():
    bpy.utils.unregister_class(OBJECT_OT_transfer_vertex_groups_from_active)
    bpy.utils.unregister_class(OBJECT_OT_delete_unused_vertex_groups)
    bpy.utils.unregister_class(OBJECT_OT_confirm_delete_unused_bones)
    bpy.utils.unregister_class(OBJECT_MT_vertex_tools)
    bpy.types.MESH_MT_vertex_group_context_menu.remove(draw_vertex_group_menu)

if __name__ == "__main__":
    register()