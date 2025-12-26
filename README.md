# DragOnTower

> **Visual Prime Tower Plugin for Ultimaker Cura**
> 
> Drag, position, and visualize your prime tower directly on the build plate - no more guessing where it will print!

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Cura Version](https://img.shields.io/badge/Cura-5.x-orange.svg)](https://ultimaker.com/software/ultimaker-cura)
[![Python Version](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)

## 🎯 What is DragOnTower?

DragOnTower adds an interactive 3D representation of the prime tower to your Cura build plate. Instead of just seeing coordinates in settings, you can now:

- **See** the exact prime tower location and size in 3D
- **Drag** it to the perfect position on your build plate
- **Sync** automatically with Cura's prime tower settings
- **Prevent** accidental modifications with built-in protections

Perfect for multi-material prints where prime tower placement matters!

## ✨ Features

### Visual Representation
- 3D cylinder showing exact prime tower position and size
- Real-time synchronization with Cura settings
- Automatic visibility based on extruder usage
- Matches Cura's prime tower shadow behavior

### Interactive Positioning
- Drag the tower anywhere on the build plate
- Automatic boundary constraints (stays within printable area)
- Y-axis locked to build plate (no vertical movement)
- Rotation prevented (prime tower is always upright)

### Smart Protection
- Cannot be sliced or printed (visual only)
- Blocks incompatible tools when selected (rotate, mirror, paint, per-model settings)
- Prevents support blocker additions
- Auto-recreates if accidentally deleted
- Cannot have per-model settings applied

### Seamless Integration
- Appears/disappears based on:
  - Prime tower enabled in settings
  - Multiple extruders in use (2+)
- Updates when you change:
  - Prime tower size
  - Prime tower position
  - Extruder assignments
  - Support/adhesion settings

## 🚀 Usage

### Basic Usage

1. **Enable Prime Tower** in Cura settings
2. **Load at least 2 extruders** (or assign different extruders to support/adhesion)
3. **See the visual tower** appear automatically
4. **Drag it** to your desired position
5. **Slice** as normal - the visual tower won't be printed

### Tips

- **Positioning**: The tower stays within build plate boundaries automatically
- **Selection**: Click the tower to select it (incompatible tools will be disabled)
- **Deletion**: If you delete it, it will reappear automatically if conditions are met
- **Settings**: Changes to prime tower size/position in settings update the visual instantly
- **Deselection**: Click elsewhere to deselect and re-enable all tools

### Supported Settings

The visual tower responds to these settings:
- `prime_tower_enable` - Show/hide the tower
- `prime_tower_size` - Diameter of the tower
- `prime_tower_position_x` - X coordinate
- `prime_tower_position_y` - Y coordinate
- Extruder usage (support, adhesion, models)

## 🔧 Technical Details

### Requirements
- **Cura Version**: 5.0+
- **API Level**: 8
- **Python**: 3.8+
- **Dependencies**: PyQt6, Uranium, Cura libraries (included with Cura)

### Architecture

```
ProtectedSceneNode
├── Blocks SliceableObjectDecorator
├── Blocks SettingOverrideDecorator
├── Blocks child node additions
└── Returns None for getStack/setActiveExtruder

Decorators
├── NonSliceableDecorator (prevents slicing)
├── PrimeTowerRepresentationDecorator (identification)
└── TransformConstraintDecorator (marks as constrained)

Plugin Logic
├── Visibility: Matches ExtruderManager.getUsedExtruderStacks()
├── Positioning: Settings ↔ Scene coordinate conversion
├── Constraints: Y-axis locked, rotation blocked, boundaries enforced
└── Tool Management: Disables incompatible tools on selection
```

### Coordinate System

**Cura Settings** (Origin: Front-left corner or center based on machine)
- X: Left to right
- Y: Front to back (note: Y in settings)

**Scene Coordinates** (Origin: Build plate center)
- X: Left (-) to right (+)
- Z: Front (+) to back (-) (note: Z in scene)
- Y: Build plate height (locked)

The plugin automatically handles conversion between these systems.

## 🤝 Contributing

Contributions are welcome! This project was developed with extensive AI assistance and follows best practices.

## 📝 License

This project is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**.

```
DragOnTower - Visual Prime Tower Plugin for Ultimaker Cura
Copyright (C) 2025 HellAholic

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published
by the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
```

See [LICENSE](DragOnTower/NameToBeAnnouncedAfterPoll/LICENSE) for full license text.

## 🐛 Known Issues

- **Deletion**: Prime tower can be deleted by user (will auto-recreate if conditions met)
- **Multi-selection**: Behavior with multiple objects selected needs additional testing
