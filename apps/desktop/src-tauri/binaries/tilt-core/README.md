# tilt-core

`scripts/build-sidecar.sh` fills this directory with the packaged Python
service — an executable named `tilt-core` beside the `_internal` folder of
native libraries PyInstaller collects.

The directory itself is committed, empty, on purpose. `tauri.conf.json` declares
it as a bundle resource, and Tauri refuses to build against a resource path that
does not exist — so without this file, nobody could compile the shell until they
had first packaged the sidecar. Development builds do not need it at all: they
run the Python in `core/` directly.
