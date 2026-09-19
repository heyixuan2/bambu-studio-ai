"""Text- and image-to-3D generation through hosted providers (Meshy, Tripo, Rodin).

``providers/`` holds one module per service behind a common protocol; ``pipeline``
runs a task from submission to a downloaded, measured file. Nothing here prints:
progress goes to a callback and errors are raised as ``errors.GenerationError``.
"""
