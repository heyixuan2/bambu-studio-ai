"""Tool discovery helpers in common.py."""

import common


def test_versioned_blender_installs_are_tried_newest_first():
    root = "C:/Program Files/Blender Foundation"
    found = [f"{root}/Blender 4.2/blender.exe", f"{root}/Blender 4.10/blender.exe",
             f"{root}/Blender/blender.exe", f"{root}/Blender 3.6/blender.exe"]
    assert common.newest_first(found) == [
        f"{root}/Blender 4.10/blender.exe", f"{root}/Blender 4.2/blender.exe",
        f"{root}/Blender 3.6/blender.exe", f"{root}/Blender/blender.exe"]
