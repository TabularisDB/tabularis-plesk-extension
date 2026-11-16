#!/usr/bin/env bash
set -euo pipefail

lab_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
container_name="${PLESK_LAB_CONTAINER:-tabularis-plesk-lab}"
image="${PLESK_LAB_IMAGE:-plesk/plesk@sha256:1d0911e7fcb3a2d1d33d06aa30e3da6334daed720ea8106e113a05c0ac2e8924}"

if docker container inspect "$container_name" >/dev/null 2>&1; then
    label="$(docker inspect --format '{{index .Config.Labels "com.tabularis.purpose"}}' "$container_name")"
    if [[ "$label" != "plesk-extension-lab" ]]; then
        echo "Refusing to change an existing container without the lab label." >&2
        exit 1
    fi
    docker start "$container_name" >/dev/null
else
    # These systemd options follow the official https://github.com/plesk/docker image.
    # No host Docker socket, host networking, database ports, or public panel ports.
    docker run -d --name "$container_name" --hostname "${PLESK_LAB_HOSTNAME:-plesk-lab.test}" \
        --label com.tabularis.purpose=plesk-extension-lab \
        --restart unless-stopped --memory 4g --cpus 3 \
        --tmpfs /tmp --tmpfs /run --tmpfs /run/lock \
        -v /sys/fs/cgroup:/sys/fs/cgroup \
        --cgroupns=host --cap-add SYS_ADMIN --security-opt apparmor=unconfined \
        -p "127.0.0.1:${PLESK_LAB_PANEL_PORT:-18443}:8443" \
        -p "127.0.0.1:${PLESK_LAB_PANEL_HTTP_PORT:-18880}:8880" \
        -p "127.0.0.1:${PLESK_LAB_HTTP_PORT:-18086}:80" \
        -p "127.0.0.1:${PLESK_LAB_HTTPS_PORT:-18444}:443" \
        "$image" >/dev/null
fi

ready=false
for ((attempt=0; attempt<90; attempt++)); do
    if docker exec "$container_name" test -f /root/.container_started 2>/dev/null; then
        ready=true
        break
    fi
    sleep 2
done
if [[ "$ready" != true ]]; then
    echo "Plesk initialization has not completed; inspect this lab container before retrying." >&2
    exit 1
fi
python3 "$lab_dir/provision.py" --bootstrap-only
echo "Local panel: https://127.0.0.1:${PLESK_LAB_PANEL_PORT:-18443}/"
echo "Run python3 $lab_dir/provision.py to provision the databases."
