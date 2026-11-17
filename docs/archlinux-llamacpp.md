# llama.cpp and Arch-family systems

Arch supports read-only hardware planning and portable GGUF operations:

```bash
bash setup.sh ai server hardware
bash setup.sh ai server plan
bash setup.sh ai llamacpp gguf-context /absolute/model.gguf
```

Managed installation supports the Arch family on systemd hosts with configured native repositories. Storage can be local or on a selected mount.
See the [server guide](../INSTALL-LLAMACPP-FIRST.md) and
[GGUF operations](unified-setup.md#complete-gguf-bundles-and-old-selection-recovery).
A working Arch package adapter does not establish managed AI installation support.
