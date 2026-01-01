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

from typing import Optional

from PyQt6.QtCore import QObject

from UM.Extension import Extension
from UM.Application import Application
from UM.Logger import Logger
from UM.Scene.SceneNode import SceneNode
from UM.Scene.SceneNodeDecorator import SceneNodeDecorator
from UM.Scene.Selection import Selection
from UM.Math.Vector import Vector
from UM.Math.Quaternion import Quaternion
from UM.Math.Color import Color
from UM.Operations.GravityOperation import GravityOperation
from UM.Resources import Resources
from UM.View.GL.OpenGL import OpenGL

from cura.Settings.ExtruderManager import ExtruderManager
from cura.Scene.SliceableObjectDecorator import SliceableObjectDecorator
from cura.Settings.SettingOverrideDecorator import SettingOverrideDecorator

from .PrimeTowerMeshBuilder import PrimeTowerMeshBuilder


class ProtectedSceneNode(SceneNode):
    """SceneNode that blocks decorator and child node additions to prevent unwanted modifications."""
    
    shader = None  # Shared shader for all prime tower instances
    collision_detected = False  # Track collision state for color changes
    
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
    
    def render(self, renderer):
        """Custom render method to apply cyan color to prime tower with proper shading."""
        if not ProtectedSceneNode.shader:
            ProtectedSceneNode.shader = OpenGL.getInstance().createShaderProgram(
                Resources.getPath(Resources.Shaders, "object.shader"))

        # Change color based on collision state
        if ProtectedSceneNode.collision_detected:
            color = Color(1.0, 0.0, 0.0, 1.0)  # Red when colliding
        else:
            color = Color(0.0, 0.8, 0.9, 1.0)  # Cyan when valid
        
        ProtectedSceneNode.shader.setUniformValue("u_diffuseColor", color)
        
        batch = renderer.getNamedBatch("prime_tower_visual")
        if not batch:
            batch = renderer.createRenderBatch(shader=ProtectedSceneNode.shader)
            renderer.addRenderBatch(batch, name="prime_tower_visual")
        
        batch.addItem(self.getWorldTransformation(copy=False), self.getMeshData())
        return True


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
        super().__init__()
        
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
        self._original_base_size: float = 0.0
        self._original_base_height: float = 0.0
        self._original_base_curve: float = 0.0
        self._original_max_height: float = 0.0
        self._machine_width: float = self.DEFAULT_MACHINE_WIDTH
        self._machine_depth: float = self.DEFAULT_MACHINE_DEPTH
        self._machine_center_is_zero: bool = False
        
        # Track BuildVolume reference for reconnecting signals
        self._build_volume = None
        
        # Track sliceable objects for height changes
        self._tracked_objects = set()
        
        # Scale tool deferred update state
        self._pending_scale_update: bool = False
        self._pending_scale_value: float = 1.0
        self._pending_original_settings: Optional[tuple] = None  # (size, pos_x, pos_y) before scale operation
        
        self._application.globalContainerStackChanged.connect(self._onGlobalStackChanged)
        self._application.getController().toolOperationStopped.connect(self._onToolOperationStopped)
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
        """Handle global container stack changes (printer switching)."""
        # Set signal to prevent regeneration during switch
        self._settings_update_in_progress = True
        
        try:
            # Disconnect old stack signals
            if self._global_stack:
                try:
                    self._global_stack.propertyChanged.disconnect(self._onSettingValueChanged)
                except:
                    pass
            
            # Remove ALL prime tower mesh representations (including orphaned ones)
            self._removeAllPrimeTowerNodes()
            
            # Clear collision state since BuildVolume will be recalculated for new printer
            ProtectedSceneNode.collision_detected = False
            
            # Clear all internal references to position and settings
            self._build_plate_y = 0.0
            self._original_mesh_diameter = 0.0
            self._original_base_size = 0.0
            self._original_base_height = 0.0
            self._original_base_curve = 0.0
            self._original_max_height = 0.0
            self._pending_scale_update = False
            self._pending_scale_value = 1.0
            self._pending_original_settings = None
            self._tracked_objects.clear()
            
            # Get new global stack
            self._global_stack = self._application.getGlobalContainerStack()
            
            # Connect to new printer and generate prime tower
            if self._global_stack:
                self._global_stack.propertyChanged.connect(self._onSettingValueChanged)
                self._machine_width = self._global_stack.getProperty("machine_width", "value") or self.DEFAULT_MACHINE_WIDTH
                self._machine_depth = self._global_stack.getProperty("machine_depth", "value") or self.DEFAULT_MACHINE_DEPTH
                self._machine_center_is_zero = bool(self._global_stack.getProperty("machine_center_is_zero", "value"))
                
                # Reconnect to the NEW BuildVolume for the new printer
                if self._build_volume:
                    try:
                        self._build_volume.raftThicknessChanged.disconnect(self._checkTowerCollision)
                    except:
                        pass
                
                self._build_volume = self._application.getBuildVolume()
                if self._build_volume:
                    self._build_volume.raftThicknessChanged.connect(self._checkTowerCollision)
        
        finally:
            # Turn signal back to normal
            self._settings_update_in_progress = False
        
        # Now create tower for new printer
        if self._global_stack:
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
        if self._creating_prime_tower or self._settings_update_in_progress:
            return
        
        if self._prime_tower_node and self._prime_tower_node.getParent() is None:
            self._prime_tower_node = None
        
        if source and source.callDecoration("isSliceable"):
            self._checkAndCreatePrimeTowerNode()
            # Track this object's transformations to detect height changes
            if source not in self._tracked_objects:
                self._tracked_objects.add(source)
                try:
                    source.transformationChanged.connect(self._onSliceableObjectTransformed)
                except:
                    pass
            # Check if max height changed (model added or moved)
            if self._prime_tower_node:
                new_max_height = self._getMaxModelHeight()
                if abs(new_max_height - self._original_max_height) > 0.01:  # Tolerance for floating point
                    self._regenerateMesh()
        elif source and source.getParent() is None:
            # Object removed - stop tracking
            if source in self._tracked_objects:
                self._tracked_objects.discard(source)
                try:
                    source.transformationChanged.disconnect(self._onSliceableObjectTransformed)
                except:
                    pass
            self._checkAndCreatePrimeTowerNode()
        elif not self._prime_tower_node:
            self._checkAndCreatePrimeTowerNode()
    
    def _onSliceableObjectTransformed(self, node: SceneNode):
        """Check if max height changed when a sliceable object is transformed.
        
        This is connected to each sliceable object's transformationChanged signal
        to detect when models are moved, scaled, or rotated that might affect
        the required prime tower height.
        """
        if not self._prime_tower_node or self._settings_update_in_progress:
            return
        
        try:
            new_max_height = self._getMaxModelHeight()
            if abs(new_max_height - self._original_max_height) > 0.01:
                self._regenerateMesh()
        except Exception as e:
            Logger.log("w", "Error checking height change: %s", str(e))
    
    def _onToolOperationStopped(self, event):
        """Apply pending scale changes after tool operation completes.
        
        When the scale tool is released, this calculates the new tower size from the
        scaled bounding box and updates both size and position settings to maintain
        the tower's center position.
        """
        if not (self._pending_scale_update and self._prime_tower_node and self._global_stack):
            return
        
        try:
            self._pending_scale_update = False
            stored_settings = self._pending_original_settings
            self._pending_original_settings = None
            
            bbox = self._prime_tower_node.getBoundingBox()
            if not bbox or stored_settings is None:
                Logger.log("w", "Failed to apply scale: missing bounding box or stored settings")
                return
            
            original_size, original_pos_x, original_pos_y = stored_settings
            
            # Calculate new tower size from scaled bounding box
            # Bounding box includes the base, so subtract base margins from both sides
            bbox_size = max(bbox.width, bbox.depth)
            base_size = self._global_stack.getProperty("prime_tower_base_size", "value") or original_size
            new_tower_size = bbox_size - (2 * base_size)
            
            # Ensure size is valid
            if new_tower_size <= 0:
                Logger.log("w", "Invalid tower size after scale: %.2f", new_tower_size)
                return
            
            # Calculate center position from original settings
            corner_x = original_pos_x
            corner_z = -original_pos_y
            if not self._machine_center_is_zero:
                corner_x -= self._machine_width / 2
                corner_z += self._machine_depth / 2
            
            original_radius = original_size / 2.0
            center_x = corner_x - original_radius
            center_z = corner_z - original_radius
            
            # Calculate new corner position to maintain center with new size
            new_radius = new_tower_size / 2.0
            new_corner_x = center_x + new_radius
            new_corner_z = center_z + new_radius
            
            # Convert back to settings coordinates
            new_pos_x = new_corner_x
            new_pos_z = new_corner_z
            if not self._machine_center_is_zero:
                new_pos_x += self._machine_width / 2
                new_pos_z -= self._machine_depth / 2
            new_pos_y = -new_pos_z
            
            # Update both size and position atomically
            self._settings_update_in_progress = True
            self._global_stack.setProperty("prime_tower_size", "value", new_tower_size)
            self._global_stack.setProperty("prime_tower_position_x", "value", new_pos_x)
            self._global_stack.setProperty("prime_tower_position_y", "value", new_pos_y)
            self._settings_update_in_progress = False
            
            # Reset scale to 1.0 since we applied it to the setting
            self._prime_tower_node.setScale(Vector(1.0, 1.0, 1.0))
            
        except Exception as e:
            Logger.log("e", "Error applying scale changes: %s", str(e))
            self._settings_update_in_progress = False
    
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
        
        # Settings that affect mesh geometry (require regeneration)
        mesh_geometry_settings = [
            "prime_tower_size",
            "prime_tower_base_size",
            "prime_tower_base_height",
            "prime_tower_base_curve_magnitude",
            "layer_height"
        ]
        
        # Settings that only affect position
        position_settings = [
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
        
        if key == "prime_tower_enable":
            self._checkAndCreatePrimeTowerNode()
        elif key in mesh_geometry_settings:
            if self._prime_tower_node:
                self._regenerateMesh()
        elif key in position_settings:
            if self._prime_tower_node:
                self._updateNodePosition()
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
            # Generate the mesh
            mesh_data = self._generateTowerMesh()
            
            if not mesh_data:
                Logger.log("e", "Failed to generate prime tower mesh")
                return
            
            protected_node = ProtectedSceneNode()
            protected_node.setMeshData(mesh_data)
            protected_node.setName("Prime Tower Visual")
            
            self._prime_tower_node = protected_node
            
            self._prime_tower_node.addDecorator(NonSliceableDecorator())
            self._prime_tower_node.addDecorator(PrimeTowerRepresentationDecorator())
            self._prime_tower_node.addDecorator(TransformConstraintDecorator())
            self._prime_tower_node.setSelectable(True)
            
            self._scene.getRoot().addChild(self._prime_tower_node)
            self._updateNodePosition()
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
    
    def _removeAllPrimeTowerNodes(self):
        """Remove all prime tower nodes from the scene, including orphaned ones."""
        # First remove our tracked node
        if self._prime_tower_node:
            self._removePrimeTowerNode()
        
        # Then search for any orphaned prime tower nodes and remove them
        root = self._scene.getRoot()
        nodes_to_remove = []
        
        for node in root.getChildren():
            # Check if it's a prime tower by name or decorator
            if node.getName() == "Prime Tower Visual":
                nodes_to_remove.append(node)
            else:
                # Check for PrimeTowerRepresentationDecorator
                for decorator in node.getDecorators():
                    if hasattr(decorator, 'isPrimeTowerRepresentation') and decorator.isPrimeTowerRepresentation():
                        nodes_to_remove.append(node)
                        break
        
        # Remove all found nodes
        for node in nodes_to_remove:
            try:
                if Selection.isSelected(node):
                    Selection.remove(node)
                root.removeChild(node)
            except Exception as e:
                Logger.log("w", f"Failed to remove prime tower node: {e}")
        
        # Ensure our reference is cleared
        self._prime_tower_node = None
        self._prime_tower_was_selected = False
    
    def _generateTowerMesh(self):
        """Generate tower mesh based on current settings.
        
        Returns:
            MeshData: The generated mesh data, or None if generation failed.
        """
        if not self._global_stack:
            return None
        
        # Get prime tower settings
        tower_size = self._global_stack.getProperty("prime_tower_size", "value") or self.DEFAULT_TOWER_SIZE
        base_size = self._global_stack.getProperty("prime_tower_base_size", "value") or tower_size
        base_height = self._global_stack.getProperty("prime_tower_base_height", "value") or 0.0
        base_curve_magnitude = self._global_stack.getProperty("prime_tower_base_curve_magnitude", "value") or 4.0
        layer_height = self._global_stack.getProperty("layer_height", "value") or 0.2
        
        # Get the maximum model height from scene
        tower_height = self._getMaxModelHeight()
        if not tower_height or tower_height <= 10:
            tower_height = 20.0  # Fallback height

        # Generate the mesh
        mesh_data = PrimeTowerMeshBuilder.buildPrimeTowerMesh(
            tower_size=tower_size,
            tower_height=tower_height,
            base_size=base_size,
            base_height=base_height,
            base_curve_magnitude=base_curve_magnitude,
            layer_height=layer_height
        )
        
        if mesh_data:
            # Store original settings for comparison
            self._original_mesh_diameter = tower_size
            self._original_base_size = base_size
            self._original_base_height = base_height
            self._original_base_curve = base_curve_magnitude
            self._original_max_height = tower_height
        
        return mesh_data
        
    def _regenerateMesh(self):
        """Regenerate tower mesh when geometry settings change."""
        if not self._prime_tower_node or not self._global_stack:
            return
        
        self._settings_update_in_progress = True
        
        try:
            mesh_data = self._generateTowerMesh()
            
            if mesh_data:
                self._prime_tower_node.setMeshData(mesh_data)
                
                # Update position after mesh change
                self._updateNodePosition()        
        finally:
            self._settings_update_in_progress = False
    
    def _updateNodePosition(self):
        """Update node position from prime tower position settings."""
        if not self._prime_tower_node or not self._global_stack:
            return
        
        self._settings_update_in_progress = True
        
        try:
            tower_size = self._global_stack.getProperty("prime_tower_size", "value") or self.DEFAULT_TOWER_SIZE
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
            
            gravity_op = GravityOperation(self._prime_tower_node)
            gravity_op.redo()
            self._build_plate_y = float(self._prime_tower_node.getPosition().y)
            
            position = Vector(scene_x, self._build_plate_y, scene_z)
            self._prime_tower_node.setPosition(position, SceneNode.TransformSpace.World)
            self._checkTowerCollision()
        
        finally:
            self._settings_update_in_progress = False
    
    def _checkTowerCollision(self):
        """Check BuildVolume's error areas to determine if prime tower is in invalid position."""
        if not self._prime_tower_node:
            return
        
        try:
            if not self._build_volume:
                return
            
            # Check if BuildVolume has any error areas (which includes prime tower errors)
            has_errors = self._build_volume.hasErrors()
            
            if has_errors != ProtectedSceneNode.collision_detected:
                ProtectedSceneNode.collision_detected = has_errors
                # Force a re-render by marking node as changed
                self._prime_tower_node.transformationChanged.emit(self._prime_tower_node)
        except Exception as e:
            Logger.log("w", f"Error checking BuildVolume error state: {e}")
    
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
                constrained_position = Vector(float(constrained_x), float(constrained_y), float(constrained_z))
                self._prime_tower_node.setPosition(constrained_position, SceneNode.TransformSpace.World)
            
            self._updateSettingsFromNode()
            self._checkTowerCollision()
        finally:
            self._settings_update_in_progress = False
    
    def _getMaxModelHeight(self) -> float:
        """Get the maximum height of all sliceable objects in the scene."""
        max_height = 0.0
        for node in self._scene.getRoot().getAllChildren():
            if node.callDecoration("isSliceable") and node.getMeshData():
                bbox = node.getBoundingBox()
                if bbox:
                    node_height = bbox.maximum.y
                    if node_height > max_height:
                        max_height = node_height
        return float(max_height)
    
    def _updateSettingsFromNode(self):
        """Update prime tower settings from node position and scale.
        
        This method handles two scenarios:
        1. Scale tool active: Defers updates until tool is released to avoid constant regeneration
        2. Position changes: Updates position settings immediately
        """
        if not self._prime_tower_node or not self._global_stack or self._settings_update_in_progress:
            return
        
        self._settings_update_in_progress = True
        
        try:
            # Check if scale tool is currently active
            controller = self._application.getController()
            active_tool = controller.getActiveTool()
            scale_tool_active = active_tool and active_tool.getPluginId() == "ScaleTool"
            
            # Check for scale transformation
            scale = self._prime_tower_node.getScale()
            scale_factor = max(scale.x, scale.z)
            
            if abs(scale_factor - 1.0) > 0.01:
                if scale_tool_active:
                    # Defer updates while scale tool is active
                    if self._pending_original_settings is None:
                        # Store original settings on first scale change
                        original_size = self._global_stack.getProperty("prime_tower_size", "value")
                        original_x = self._global_stack.getProperty("prime_tower_position_x", "value")
                        original_y = self._global_stack.getProperty("prime_tower_position_y", "value")
                        self._pending_original_settings = (original_size, original_x, original_y)
                    
                    self._pending_scale_update = True
                    self._pending_scale_value = float(scale_factor)
                    return
                else:
                    # Tool not active - apply scale immediately
                    new_tower_size = self._original_mesh_diameter * scale_factor
                    self._global_stack.setProperty("prime_tower_size", "value", new_tower_size)
                    self._prime_tower_node.setScale(Vector(1.0, 1.0, 1.0))
                    return
            
            # Don't update position while scale tool is active (prevents shadow movement)
            if scale_tool_active:
                return
            
            # Only update position
            position = self._prime_tower_node.getWorldPosition()
            tower_size = self._original_mesh_diameter
            
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
        
        finally:
            self._settings_update_in_progress = False
