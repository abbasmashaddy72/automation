# Laravel workflows

Local developer runtimes use Lerd through the unified toolkit. Production server provisioning and deployment use the independently copyable [Laravel toolkit](../laravel/README.md).

Copy the entire `laravel/` folder to another repository/server; it needs no parent scripts, Python libraries or root `.env`. The public entrypoints are `laravel-provision.sh` and `laravel-deploy.sh`. All Laravel configuration templates, helpers, tests and documentation are inside that folder. Optional `bash setup.sh laravel provision|deploy ...` delegates without changing standalone behavior.

Read the bundled [operations](../laravel/docs/operations.md), [verification](../laravel/docs/verification.md), and [reference review](../laravel/docs/references.md) before production use. Native container evidence and real-systemd/SSH/firewall/public-TLS verification are distinct.
