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

from . import DragOnTower


def getMetaData():
    """Return plugin metadata."""
    return {}


def register(app):
    """Register the plugin with Cura."""
    return {"extension": DragOnTower.DragOnTower()}
