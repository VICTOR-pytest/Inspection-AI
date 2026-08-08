# Vision Module

This module will contain all computer vision logic for the Inspection AI system.

## Planned Sub-modules

| Directory    | Responsibility                                      |
|--------------|-----------------------------------------------------|
| `capture/`   | Frame capture from cameras (USB, IP, industrial)    |
| `detection/` | Product detection and classification models         |
| `weight/`    | Weight validation integration                       |
| `barcode/`   | Barcode / QR-code reading                           |
| `workers/`   | Background workers processing the vision pipeline   |

## Status

🚧 **Not implemented — Sprint 1 foundation only.**

Future sprints will integrate OpenCV, YOLO, and other vision libraries here.
