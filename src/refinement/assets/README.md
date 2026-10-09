# YuNet repository asset

`face_detection_yunet_2026may.onnx` is redistributed under the adjacent
`LICENSE.YuNet` (MIT, copyright Shiqi Yu). Retain that notice in distributions.

- Upstream: https://github.com/opencv/opencv_zoo
- Revision: `47534e27c9851bb1128ccc0102f1145e27f23f98`
- Path: `models/face_detection_yunet/face_detection_yunet_2026may.onnx`
- Bytes: 229738
- SHA-256: `ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0`

The actual Git LFS payload was independently downloaded and hashed, rather than
storing the LFS pointer. This dynamic-input model is qualified with standard
`opencv-python==5.0.0.93` / NumPy 2.5.3 on Windows CPython 3.14, using the CPU
DNN path. No CUDA or external runtime is selected. There are no automatic
downloads or model scans. Restore this exact asset from the repository if its
size/hash check fails; the detector refuses native loading of other bytes.
