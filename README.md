# Occurrence Reviewer 0.4.7 diagnostic build

Adds a **Refresh layers** button beside **Start / resume** and **Settings**. The refresh rescans the current QGIS project for point-vector layers, preserves the currently selected layer by layer ID where possible, selects the first available point layer otherwise, updates the source-field list and records the refresh in the diagnostic log.

The Move-key diagnostic system, QGIS 3.44 behaviour and Linux-safe source handling remain unchanged.
