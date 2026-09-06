# Deploy secret isolation

The pipeline deploy backend treats repository-controlled Docker Compose input as untrusted.

## Boundary

`DockerDeployService` builds and pushes the governed release image before invoking Compose. The Compose phase is image-only: repository Compose files may reference `${DOR_IMAGE_TAG}` and may orchestrate the already-built image, but they do not receive the API/worker process environment.

The Compose subprocess receives exactly:

- `DOR_IMAGE_TAG` for the governed image selected by DOR;
- a fixed system `PATH` used only to locate the Docker CLI;
- `COMPOSE_DISABLE_ENV_FILE=1` so repository `.env` files cannot extend the interpolation environment.

Control-plane credentials such as database URLs, JWT signing material, authority signing keys, object-storage credentials, GitHub tokens, and model credentials are not copied into the Compose subprocess environment.

The same boundary applies to rollback Compose execution.

## Compose policy

Before `docker compose up`, DOR fails closed if the repository Compose file:

- references any environment variable other than `DOR_IMAGE_TAG`, including both `${VAR}` and `$VAR` forms;
- requests a Compose-time `build`;
- requests `env_file` access;
- declares file-backed Compose `secrets` or `configs`;
- requests privileged mode, host namespace modes, host devices, absolute host volumes, or the Docker socket.

These checks prevent repository input from turning the deployer process into a secret oracle or host-file reader. They do not make arbitrary tenant workloads trusted; deployment network isolation and production infrastructure separation remain independent controls.

## Regression contract

`tests/execution/test_deploy_secret_isolation.py` proves that normal and rollback Compose invocations receive only the minimal environment and that malicious interpolation/host-read surfaces fail before Docker Compose is invoked.
