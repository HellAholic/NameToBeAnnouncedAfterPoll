# DragOnTower Plugin - Prime Tower Mesh Builder
# Created by HellAholic 2025
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import math
from typing import Optional

from UM.Mesh.MeshBuilder import MeshBuilder
from UM.Mesh.MeshData import MeshData
from UM.Logger import Logger


class PrimeTowerMeshBuilder:
    """Builds a mesh representation of the prime tower based on Cura settings."""
    
    # Number of segments for cylinder approximation
    SEGMENTS = 32
    
    @staticmethod
    def buildPrimeTowerMesh(
        tower_size: float,
        tower_height: float,
        base_size: float = 0.0,
        base_height: float = 0.0,
        base_curve_magnitude: float = 4.0,
        layer_height: float = 0.2
    ) -> Optional[MeshData]:
        """Generate a prime tower mesh with optional base.
        
        Args:
            tower_size: Diameter of the main tower body
            tower_height: Total height of the tower
            base_size: Additional margin extending beyond tower edge (in mm from tower outer edge)
            base_height: Height of the base section
            base_curve_magnitude: Power curve exponent for base slope (default 4.0, higher=slimmer)
            
        Returns:
            MeshData object representing the tower, or None on failure
        """
        try:
            tower_radius = tower_size / 2.0
            # Base size is the margin beyond the tower edge, so add it to the tower radius
            base_radius = tower_radius + base_size if base_size > 0 else tower_radius
            
            # Calculate transition zone if there's a base
            has_base = base_size > 0 and base_height > 0
            
            if has_base:
                return PrimeTowerMeshBuilder._buildTowerWithBase(
                    tower_radius=tower_radius,
                    tower_height=tower_height,
                    base_radius=base_radius,
                    base_height=base_height,
                    base_curve_magnitude=base_curve_magnitude,
                    layer_height=layer_height
                )
            else:
                # Simple cylinder without base
                return PrimeTowerMeshBuilder._buildSimpleCylinder(
                    radius=tower_radius,
                    height=tower_height
                )
                
        except Exception as e:
            Logger.log("e", f"Failed to build prime tower mesh: {e}")
            return None
    
    @staticmethod
    def _buildSimpleCylinder(radius: float, height: float) -> MeshData:
        """Build a simple cylindrical tower."""
        builder = MeshBuilder()
        
        angle_step = 2 * math.pi / PrimeTowerMeshBuilder.SEGMENTS
        
        # Generate vertices for bottom and top rings
        bottom_verts = []
        top_verts = []
        
        for i in range(PrimeTowerMeshBuilder.SEGMENTS):
            angle = i * angle_step
            x = radius * math.cos(angle)
            z = radius * math.sin(angle)
            bottom_verts.append((x, 0, z))
            top_verts.append((x, height, z))
        
        # Build bottom cap (triangles from center to ring) - CCW when viewed from below
        for i in range(PrimeTowerMeshBuilder.SEGMENTS):
            next_i = (i + 1) % PrimeTowerMeshBuilder.SEGMENTS
            builder.addFaceByPoints(
                0, 0, 0,  # Center
                bottom_verts[i][0], bottom_verts[i][1], bottom_verts[i][2],
                bottom_verts[next_i][0], bottom_verts[next_i][1], bottom_verts[next_i][2]
            )
        
        # Build side faces (quads as two triangles)
        for i in range(PrimeTowerMeshBuilder.SEGMENTS):
            next_i = (i + 1) % PrimeTowerMeshBuilder.SEGMENTS
            
            # Triangle 1
            builder.addFaceByPoints(
                bottom_verts[i][0], bottom_verts[i][1], bottom_verts[i][2],
                bottom_verts[next_i][0], bottom_verts[next_i][1], bottom_verts[next_i][2],
                top_verts[i][0], top_verts[i][1], top_verts[i][2]
            )
            # Triangle 2
            builder.addFaceByPoints(
                top_verts[i][0], top_verts[i][1], top_verts[i][2],
                bottom_verts[next_i][0], bottom_verts[next_i][1], bottom_verts[next_i][2],
                top_verts[next_i][0], top_verts[next_i][1], top_verts[next_i][2]
            )
        
        # Build top cap (triangles from center to ring)
        for i in range(PrimeTowerMeshBuilder.SEGMENTS):
            next_i = (i + 1) % PrimeTowerMeshBuilder.SEGMENTS
            builder.addFaceByPoints(
                0, height, 0,  # Center
                top_verts[i][0], top_verts[i][1], top_verts[i][2],
                top_verts[next_i][0], top_verts[next_i][1], top_verts[next_i][2]
            )
        
        builder.calculateNormals()
        return builder.build()
    
    @staticmethod
    def _buildTowerWithBase(
        tower_radius: float,
        tower_height: float,
        base_radius: float,
        base_height: float,
        base_curve_magnitude: float,
        layer_height: float
    ) -> MeshData:
        """Build a tower with a wider base using power curve slope.
        
        The base uses Cura's formula: extra_radius = base_extra_radius * ((1 - z/base_height) ^ base_curve_magnitude)
        At z=0 (bottom): full base_radius
        At z=base_height (top of base): tower_radius
        """
        builder = MeshBuilder()
        
        angle_step = 2 * math.pi / PrimeTowerMeshBuilder.SEGMENTS
        
        # Generate enough layers for smooth visual curve
        # Use layer_height as a guide but ensure minimum smoothness
        layers_from_height = int(base_height / layer_height)
        num_base_layers = max(layers_from_height, 10)  # At least 10 layers for smooth curve
        
        # Generate all vertex layers
        layers = []
        
        # Layer 0: Base bottom with base_radius
        layer_verts = []
        for i in range(PrimeTowerMeshBuilder.SEGMENTS):
            angle = i * angle_step
            x = base_radius * math.cos(angle)
            z = base_radius * math.sin(angle)
            layer_verts.append((x, 0.0, z))
        layers.append((0.0, layer_verts))
        
        # Intermediate base layers with power curve
        base_extra_radius = base_radius - tower_radius
        for layer_idx in range(1, num_base_layers):
            z_height = base_height * (layer_idx / num_base_layers)
            
            # Apply Cura's power curve formula
            z_ratio = z_height / base_height
            brim_radius_factor = pow(1.0 - z_ratio, base_curve_magnitude)
            extra_radius = base_extra_radius * brim_radius_factor
            layer_radius = tower_radius + extra_radius
            
            layer_verts = []
            for i in range(PrimeTowerMeshBuilder.SEGMENTS):
                angle = i * angle_step
                x = layer_radius * math.cos(angle)
                z = layer_radius * math.sin(angle)
                layer_verts.append((x, z_height, z))
            layers.append((z_height, layer_verts))
        
        # Layer at base_height: Transition to tower_radius
        layer_verts = []
        for i in range(PrimeTowerMeshBuilder.SEGMENTS):
            angle = i * angle_step
            x = tower_radius * math.cos(angle)
            z = tower_radius * math.sin(angle)
            layer_verts.append((x, base_height, z))
        layers.append((base_height, layer_verts))
        
        # Top layer: Tower top with tower_radius
        layer_verts = []
        for i in range(PrimeTowerMeshBuilder.SEGMENTS):
            angle = i * angle_step
            x = tower_radius * math.cos(angle)
            z = tower_radius * math.sin(angle)
            layer_verts.append((x, tower_height, z))
        layers.append((tower_height, layer_verts))
        
        # Build bottom cap - CCW when viewed from below for correct normals
        bottom_verts = layers[0][1]
        for i in range(PrimeTowerMeshBuilder.SEGMENTS):
            next_i = (i + 1) % PrimeTowerMeshBuilder.SEGMENTS
            builder.addFaceByPoints(
                0, 0, 0,  # Center
                bottom_verts[i][0], bottom_verts[i][1], bottom_verts[i][2],
                bottom_verts[next_i][0], bottom_verts[next_i][1], bottom_verts[next_i][2]
            )
        
        # Build side faces between all consecutive layers
        for layer_idx in range(len(layers) - 1):
            curr_height, curr_verts = layers[layer_idx]
            next_height, next_verts = layers[layer_idx + 1]
            
            for i in range(PrimeTowerMeshBuilder.SEGMENTS):
                next_i = (i + 1) % PrimeTowerMeshBuilder.SEGMENTS
                # Triangle 1
                builder.addFaceByPoints(
                    curr_verts[i][0], curr_verts[i][1], curr_verts[i][2],
                    curr_verts[next_i][0], curr_verts[next_i][1], curr_verts[next_i][2],
                    next_verts[i][0], next_verts[i][1], next_verts[i][2]
                )
                # Triangle 2
                builder.addFaceByPoints(
                    next_verts[i][0], next_verts[i][1], next_verts[i][2],
                    curr_verts[next_i][0], curr_verts[next_i][1], curr_verts[next_i][2],
                    next_verts[next_i][0], next_verts[next_i][1], next_verts[next_i][2]
                )
        
        # Build top cap
        top_verts = layers[-1][1]
        top_height = layers[-1][0]
        for i in range(PrimeTowerMeshBuilder.SEGMENTS):
            next_i = (i + 1) % PrimeTowerMeshBuilder.SEGMENTS
            builder.addFaceByPoints(
                0, top_height, 0,  # Center
                top_verts[i][0], top_verts[i][1], top_verts[i][2],
                top_verts[next_i][0], top_verts[next_i][1], top_verts[next_i][2]
            )
        
        builder.calculateNormals()
        return builder.build()
