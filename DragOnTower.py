# DragOnTower (name to be updated after poll) Plugin - Visual Prime Tower Representation Plugin for Cura
# Created by HellAholic 2025
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

import os
from typing import Optional

from PyQt6.QtCore import QObject
from matplotlib.widgets import ToolLineHandles

from UM import Tool
from UM.Extension import Extension
from UM.Application import Application
from UM.Logger import Logger
from UM.Scene.SceneNode import SceneNode
from UM.Scene.SceneNodeDecorator import SceneNodeDecorator
from UM.Scene.Selection import Selection
from UM.Math.Vector import Vector
from UM.Math.Quaternion import Quaternion
from UM.PluginRegistry import PluginRegistry
from UM.Operations.GravityOperation import GravityOperation

from cura.Settings.ExtruderManager import ExtruderManager
from cura.Scene.SliceableObjectDecorator import SliceableObjectDecorator
from cura.Settings.SettingOverrideDecorator import SettingOverrideDecorator


class ProtectedSceneNode(SceneNode):
    """SceneNode that blocks decorator and child node additions to prevent unwanted modifications."""
    
    def addDecorator(self, decorator: SceneNodeDecorator) -> None:
        if isinstance(decorator, (SliceableObjectDecorator, SettingOverrideDecorator)):
            Logger.log("w", "Cannot add decorator %s to prime tower representation", type(decorator).__name__)
            return
        super().addDecorator(decorator)
    
    def addChild(self, scene_node: SceneNode) -> None:
        """Block adding child nodes (e.g., support blockers)."""
        Logger.log("w", "Cannot add child nodes to prime tower representation")
    
    def callDecoration(self, function: str, *args, **kwargs):
        """Block settings-related decoration calls."""
        blocked_functions = ["getStack", "setActiveExtruder", "getActiveExtruder"]
        if function in blocked_functions:
            return None
        
        return super().callDecoration(function, *args, **kwargs)


class NonSliceableDecorator(SceneNodeDecorator):
    """Marks node as non-sliceable."""
    
    def __deepcopy__(self, memo):
        return NonSliceableDecorator()
    
    def isSliceable(self) -> bool:
        return False
    
    def isBlockSlicing(self) -> bool:
        return False


class PrimeTowerRepresentationDecorator(SceneNodeDecorator):
    """Identifies node as prime tower representation."""
    
    def __deepcopy__(self, memo):
        return PrimeTowerRepresentationDecorator()
    
    def isPrimeTowerRepresentation(self) -> bool:
        return True


class TransformConstraintDecorator(SceneNodeDecorator):
    """Constrains transforms to prevent Z-axis movement."""
    
    def __deepcopy__(self, memo):
        return TransformConstraintDecorator()


class DragOnTower(Extension, QObject):
    """Cura plugin that provides a draggable visual representation of the prime tower."""
    
    # Default machine dimensions (mm)
    DEFAULT_MACHINE_WIDTH = 200
    DEFAULT_MACHINE_DEPTH = 200
    
    # Default fallback values
    DEFAULT_TOWER_SIZE = 10.0
    DEFAULT_TOWER_RADIUS = 5.0
    
    # Transform constraint tolerance
    POSITION_TOLERANCE = 0.001
    
    # Minimum extruders required for prime tower
    MIN_EXTRUDERS_FOR_TOWER = 2
    
    def __init__(self):
        QObject.__init__(self)
        Extension.__init__(self)
        
        self._application = Application.getInstance()
        self._controller = self._application.getController()
        self._scene = self._controller.getScene()
        
        self._prime_tower_node: Optional[SceneNode] = None
        self._global_stack = None
        self._settings_update_in_progress: bool = False
        self._creating_prime_tower: bool = False
        self._prime_tower_was_selected: bool = False
        
        self._build_plate_y: float = 0.0
        self._original_mesh_diameter: float = 0.0
        self._machine_width: float = self.DEFAULT_MACHINE_WIDTH
        self._machine_depth: float = self.DEFAULT_MACHINE_DEPTH
        self._machine_center_is_zero: bool = False
        
        self._application.globalContainerStackChanged.connect(self._onGlobalStackChanged)
        self._scene.sceneChanged.connect(self._onSceneChanged)
        self._scene.sceneChanged.connect(self._onSceneObjectsChanged)
        Selection.selectionChanged.connect(self._onSelectionChanged)
        
        self._onGlobalStackChanged()

    def _toggleTools(self, enable: bool):
        """Enable or disable incompatible tools based on prime tower selection."""
        tool_list = [
            "RotateTool",
            "MirrorTool",
            "PaintTool",
            "PerObjectSettingsTool",
            "SupportEraser"
        ]
        for tool in tool_list:
            try:
                self._controller.toolEnabledChanged.emit(tool, enable)
            except Exception as e:
                Logger.log("e", f"Failed to toggle tool {tool}: {e}")
                pass

    def _onSelectionChanged(self):
        """Disable incompatible tools when prime tower is selected, re-enable when deselected."""
        if not self._prime_tower_node:
            return
        
        is_prime_tower_selected = Selection.isSelected(self._prime_tower_node)
        
        if is_prime_tower_selected == self._prime_tower_was_selected:
            return
        
        self._prime_tower_was_selected = is_prime_tower_selected
        self._toggleTools(not is_prime_tower_selected)
    
    def _onGlobalStackChanged(self):
        """Handle global container stack changes."""
        if self._global_stack:
            try:
                self._global_stack.propertyChanged.disconnect(self._onSettingValueChanged)
            except:
                pass
        
        if self._prime_tower_node:
            self._removePrimeTowerNode()
        
        self._global_stack = self._application.getGlobalContainerStack()
        
        if self._global_stack:
            self._global_stack.propertyChanged.connect(self._onSettingValueChanged)
            self._machine_width = self._global_stack.getProperty("machine_width", "value") or self.DEFAULT_MACHINE_WIDTH
            self._machine_depth = self._global_stack.getProperty("machine_depth", "value") or self.DEFAULT_MACHINE_DEPTH
            self._machine_center_is_zero = bool(self._global_stack.getProperty("machine_center_is_zero", "value"))
            
            self._checkAndCreatePrimeTowerNode()
    
    def _onSceneChanged(self, source: SceneNode):
        """Update settings when prime tower node is modified."""
        if not self._prime_tower_node or self._settings_update_in_progress:
            return
        
        if self._prime_tower_node.getParent() is None:
            self._prime_tower_node = None
            return
        
        if source == self._prime_tower_node:
            self._updateSettingsFromNode()
    
    def _onSceneObjectsChanged(self, source: SceneNode):
        """Check if prime tower should be recreated or visibility changed."""
        if self._creating_prime_tower:
            return
        
        if self._prime_tower_node and self._prime_tower_node.getParent() is None:
            self._prime_tower_node = None
        
        if source and source.callDecoration("isSliceable"):
            self._checkAndCreatePrimeTowerNode()
        elif source and source.getParent() is None:
            self._checkAndCreatePrimeTowerNode()
        elif not self._prime_tower_node:
            self._checkAndCreatePrimeTowerNode()
    
    def _onSettingValueChanged(self, key: str, property_name: str):
        """Update representation when relevant settings change."""
        if property_name != "value":
            return
        
        if key == "machine_width":
            self._machine_width = self._global_stack.getProperty("machine_width", "value") or self.DEFAULT_MACHINE_WIDTH
        elif key == "machine_depth":
            self._machine_depth = self._global_stack.getProperty("machine_depth", "value") or self.DEFAULT_MACHINE_DEPTH
        elif key == "machine_center_is_zero":
            self._machine_center_is_zero = bool(self._global_stack.getProperty("machine_center_is_zero", "value"))
        
        prime_tower_settings = [
            "prime_tower_enable",
            "prime_tower_size",
            "prime_tower_position_x",
            "prime_tower_position_y"
        ]
        extruder_usage_settings = [
            "support_enable",
            "support_extruder_nr",
            "support_infill_extruder_nr",
            "support_interface_extruder_nr",
            "adhesion_extruder_nr",
            "adhesion_type",
            "raft_base_extruder_nr",
            "raft_interface_extruder_nr",
            "raft_surface_extruder_nr",
            "skirt_brim_extruder_nr"
        ]
        
        if key in prime_tower_settings:
            self._checkAndCreatePrimeTowerNode()
            if key != "prime_tower_enable" and self._prime_tower_node:
                self._updateNodeFromSettings()
        elif key in extruder_usage_settings:
            self._checkAndCreatePrimeTowerNode()
    
    def _checkAndCreatePrimeTowerNode(self):
        """Create or remove prime tower node based on settings and extruder usage."""
        if not self._global_stack:
            return
        
        prime_tower_enabled = self._global_stack.getProperty("prime_tower_enable", "value")
        
        try:
            used_extruders = ExtruderManager.getInstance().getUsedExtruderStacks()
            enabled_used_extruder_count = len([x for x in used_extruders if x.isEnabled])
        except Exception as e:
            Logger.log("w", f"Failed to get extruder stacks: {e}")
            enabled_used_extruder_count = 0
        
        should_show_tower = prime_tower_enabled and enabled_used_extruder_count >= self.MIN_EXTRUDERS_FOR_TOWER
        
        if should_show_tower and not self._prime_tower_node:
            self._createPrimeTowerNode()
        elif not should_show_tower and self._prime_tower_node:
            self._removePrimeTowerNode()
    
    def _createPrimeTowerNode(self):
        """Create the visual prime tower node."""
        self._settings_update_in_progress = True
        self._creating_prime_tower = True
        
        try:
            plugin_path = PluginRegistry.getInstance().getPluginPath(self.getPluginId())
            if not plugin_path:
                Logger.log("e", "Could not get plugin path")
                return
            
            stl_path = os.path.join(plugin_path, "resources", "prime_tower.stl")
            if not os.path.exists(stl_path):
                Logger.log("e", f"Prime tower STL not found at: {stl_path}")
                return
            
            mesh_handler = Application.getInstance().getMeshFileHandler()
            reader = mesh_handler.getReaderForFile(stl_path)
            if not reader:
                Logger.log("e", "No mesh reader found for STL file")
                return
            
            node = reader.read(stl_path)
            if not node:
                Logger.log("e", "Failed to load prime tower mesh")
                return
            
            protected_node = ProtectedSceneNode()
            protected_node.setMeshData(node.getMeshData())
            protected_node.setName("Prime Tower Visual")
            
            self._prime_tower_node = protected_node
            
            mesh_data = self._prime_tower_node.getMeshData()
            if mesh_data:
                extents = mesh_data.getExtents()
                if extents:
                    self._original_mesh_diameter = max(extents.width, extents.depth)
            
            self._prime_tower_node.addDecorator(NonSliceableDecorator())
            self._prime_tower_node.addDecorator(PrimeTowerRepresentationDecorator())
            self._prime_tower_node.addDecorator(TransformConstraintDecorator())
            self._prime_tower_node.setSelectable(True)
            
            self._scene.getRoot().addChild(self._prime_tower_node)
            self._updateNodeFromSettings()
            self._prime_tower_node.transformationChanged.connect(self._onNodeTransformChanged)
            
        finally:
            self._settings_update_in_progress = False
            self._creating_prime_tower = False
    
    def _removePrimeTowerNode(self):
        """Remove the prime tower node from the scene."""
        if not self._prime_tower_node:
            return
        
        try:
            self._prime_tower_node.transformationChanged.disconnect(self._onNodeTransformChanged)
        except (RuntimeError, TypeError):
            pass
        
        if Selection.isSelected(self._prime_tower_node):
            Selection.remove(self._prime_tower_node)
        
        self._scene.getRoot().removeChild(self._prime_tower_node)
        self._prime_tower_node = None
        self._prime_tower_was_selected = False
    
    def _updateNodeFromSettings(self):
        """Update node position and scale from prime tower settings."""
        if not self._prime_tower_node or not self._global_stack:
            return
        
        self._settings_update_in_progress = True
        
        try:
            tower_size = self._global_stack.getProperty("prime_tower_size", "value")
            setting_x = self._global_stack.getProperty("prime_tower_position_x", "value")
            setting_y = self._global_stack.getProperty("prime_tower_position_y", "value")
            
            scene_x = setting_x
            scene_z = -setting_y
            
            if not self._machine_center_is_zero:
                scene_x = scene_x - self._machine_width / 2
                scene_z = scene_z + self._machine_depth / 2
            
            radius = tower_size / 2.0
            scene_x -= radius
            scene_z -= radius
            
            if self._original_mesh_diameter > 0:
                scale_factor = tower_size / self._original_mesh_diameter
                scale_vector = Vector(scale_factor, scale_factor, scale_factor)
                self._prime_tower_node.setScale(scale_vector, SceneNode.TransformSpace.World)
            
            gravity_op = GravityOperation(self._prime_tower_node)
            gravity_op.redo()
            self._build_plate_y = self._prime_tower_node.getPosition().y
            
            position = Vector(scene_x, self._build_plate_y, scene_z)
            self._prime_tower_node.setPosition(position, SceneNode.TransformSpace.World)
        
        finally:
            self._settings_update_in_progress = False
    
    def _onNodeTransformChanged(self, node: SceneNode):
        """Constrain transforms and sync to settings when node is modified."""
        if not self._prime_tower_node or node != self._prime_tower_node or self._settings_update_in_progress:
            return
        
        self._settings_update_in_progress = True
        
        try:
            position = self._prime_tower_node.getWorldPosition()
            orientation = self._prime_tower_node.getOrientation()
            
            identity_orientation = Quaternion()
            if orientation != identity_orientation:
                self._prime_tower_node.setOrientation(identity_orientation)
            
            constrained_y = self._build_plate_y
            bbox = self._prime_tower_node.getBoundingBox()
            if bbox:
                tower_radius = max(bbox.width, bbox.depth) / 2.0
            else:
                tower_radius = self.DEFAULT_TOWER_RADIUS
            
            min_x = -self._machine_width / 2.0 + tower_radius
            max_x = self._machine_width / 2.0 - tower_radius
            min_z = -self._machine_depth / 2.0 + tower_radius
            max_z = self._machine_depth / 2.0 - tower_radius
            
            constrained_x = max(min_x, min(position.x, max_x))
            constrained_z = max(min_z, min(position.z, max_z))
            
            if (abs(position.y - constrained_y) > self.POSITION_TOLERANCE or 
                abs(position.x - constrained_x) > self.POSITION_TOLERANCE or 
                abs(position.z - constrained_z) > self.POSITION_TOLERANCE):
                constrained_position = Vector(constrained_x, constrained_y, constrained_z)
                self._prime_tower_node.setPosition(constrained_position, SceneNode.TransformSpace.World)
            
            self._updateSettingsFromNode()
        finally:
            self._settings_update_in_progress = False
    
    def _updateSettingsFromNode(self):
        """Update prime tower settings from node position and scale."""
        if not self._prime_tower_node or not self._global_stack or self._settings_update_in_progress:
            return
        
        self._settings_update_in_progress = True
        
        try:
            position = self._prime_tower_node.getWorldPosition()
            
            bbox = self._prime_tower_node.getBoundingBox()
            if bbox:
                tower_size = max(bbox.width, bbox.depth)
            else:
                tower_size = self.DEFAULT_TOWER_SIZE
            
            radius = tower_size / 2.0
            corner_x = position.x + radius
            corner_z = position.z + radius
            
            setting_x = corner_x
            setting_z = corner_z
            
            if not self._machine_center_is_zero:
                setting_x = setting_x + self._machine_width / 2
                setting_z = setting_z - self._machine_depth / 2
            
            setting_y = -setting_z
            
            self._global_stack.setProperty("prime_tower_position_x", "value", setting_x)
            self._global_stack.setProperty("prime_tower_position_y", "value", setting_y)
            self._global_stack.setProperty("prime_tower_size", "value", tower_size)
        
        finally:
            self._settings_update_in_progress = False
