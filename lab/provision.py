#!/usr/bin/env python3
"""Provision only the labelled Plesk lab; store generated passwords outside Git."""

import argparse
import json
import ipaddress
import os
from pathlib import Path
import re
import secrets
import subprocess

CONTAINER = os.environ.get("PLESK_LAB_CONTAINER", "tabularis-plesk-lab")
STATE = Path(os.environ.get("PLESK_LAB_STATE_DIR", Path.home() / ".local/state/tabularis-plesk-lab"))
HERE = Path(__file__).resolve().parent
DOMAIN = os.environ.get("PLESK_LAB_DOMAIN", "shop.example.test").lower()


def execute(arguments, *, input_text="", label="Lab command", check=True):
    result = subprocess.run(arguments, input=input_text, text=True, capture_output=True)
    if check and result.returncode:
        # Never echo raw subprocess output: a vendor error could include a credential.
        raise RuntimeError(f"{label} failed (exit {result.returncode}); inspect the lab container.")
    return result


def inside(arguments, **kwargs):
    return execute(["docker", "exec", "-i", CONTAINER, *arguments], **kwargs)


def plesk(arguments, *, password=None):
    if password is None:
        return inside(["plesk", "bin", *arguments], label=f"Plesk {arguments[0]}")
    return inside(
        ["sh", "-c", 'read -r PSA_PASSWORD; export PSA_PASSWORD; exec plesk bin "$@"', "sh", *arguments],
        input_text=password + "\n", label=f"Plesk {arguments[0]}",
    )


def panel_query(query):
    return inside(["plesk", "db", "-Ne", query], label="Panel metadata lookup").stdout.strip()


def credentials():
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    STATE.chmod(0o700)
    path = STATE / "credentials.json"
    if not path.exists():
        values = {key: secrets.token_urlsafe(30) + "aA9!" for key in (
            "admin", "customer", "system", "postgres_admin", "pg_owner", "pg_scoped",
            "mysql_owner", "mysql_scoped", "subuser",
        )}
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w") as output:
            json.dump(values, output, indent=2)
            output.write("\n")
    path.chmod(0o600)
    return json.loads(path.read_text())


def assert_lab():
    result = execute(["docker", "inspect", "--format", '{{index .Config.Labels "com.tabularis.purpose"}}', CONTAINER])
    if result.stdout.strip() != "plesk-extension-lab":
        raise RuntimeError("Refusing to provision a container without the lab label.")


def bootstrap(values):
    marker = STATE / "bootstrap-completed"
    container_id = execute(["docker", "inspect", "--format", "{{.Id}}", CONTAINER]).stdout.strip()
    # Removing the image's convenience login is mandatory before any external access.
    if not marker.exists() or marker.read_text() != container_id:
        plesk(["admin", "--set-admin-password", "-passwd", ""], password=values["admin"])
        installed = plesk(["extension", "--list"]).stdout
        if "default-login" in installed:
            plesk(["extension", "--uninstall", "default-login"])
        inside(["sh", "-c", "rm -f /etc/systemd/system/plesk-cloning.service.d/password.conf; systemctl daemon-reload"])
        marker.write_text(container_id)
        marker.chmod(0o600)
    plesk(["license", "--check-installed-license"])
    hostname = os.environ.get("PLESK_LAB_HOSTNAME")
    if hostname:
        validate_domain(hostname)
        # Docker bind-mounts /etc/hostname; hostnamectl cannot atomically replace it.
        inside(["python3", "-c", "from pathlib import Path; import subprocess,sys; Path('/etc/hostname').write_text(sys.argv[1]+'\\n'); subprocess.run(['hostname',sys.argv[1]],check=True)", hostname])
        plesk(["server_pref", "--update", "-hostname", hostname])
    public_ip = os.environ.get("PLESK_LAB_PUBLIC_IP")
    if public_ip:
        public_ip = str(ipaddress.ip_address(public_ip))
        address = execute(["docker", "inspect", "--format", '{{(index .NetworkSettings.Networks "bridge").IPAddress}}', CONTAINER]).stdout.strip()
        plesk(["ipmanage", "--update", address, "-public_ip", public_ip])
    print("Panel credentials protected in", STATE / "credentials.json")


def validate_domain(value):
    if not re.fullmatch(r"(?=.{1,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}", value):
        raise RuntimeError("The lab domain/hostname must be a valid ASCII DNS name.")


def create_fixture_accounts(values):
    if panel_query("SELECT count(*) FROM clients WHERE login='tabularis-lab'") == "0":
        plesk(["customer", "--create", "tabularis-lab", "-name", "Tabularis Lab", "-passwd", "", "-email", "lab@example.test", "-notify", "false"], password=values["customer"])
    if panel_query(f"SELECT count(*) FROM domains WHERE name='{DOMAIN}'") == "0":
        address = execute(["docker", "inspect", "--format", '{{(index .NetworkSettings.Networks "bridge").IPAddress}}', CONTAINER]).stdout.strip()
        if not address:
            raise RuntimeError("The lab requires its own default Docker bridge address.")
        plesk(["subscription", "--create", DOMAIN, "-owner", "tabularis-lab", "-ip", address,
               "-hosting", "true", "-login", "tabularis_shop", "-passwd", "", "-mail_service", "false",
               "-dns", "false", "-notify", "false"], password=values["system"])
    for name, allowed in (("LabDatabaseUser", "true"), ("LabNoDatabaseUser", "false")):
        if panel_query(f"SELECT count(*) FROM smb_roles WHERE name='{name}'") == "0":
            plesk(["role", "--create", name, "-owner", "tabularis-lab", "-databasesManagement", allowed])
    for login, role in (("dbuser@example.test", "LabDatabaseUser"), ("nodbuser@example.test", "LabNoDatabaseUser")):
        if panel_query(f"SELECT count(*) FROM smb_users WHERE login='{login}'") == "0":
            plesk(["user", "--create", login, "-owner", "tabularis-lab", "-role", role, "-passwd", "",
                   "-cname", login, "-external-email", login, "-subscription-name", DOMAIN], password=values["subuser"])


def seed_databases(values):
    if inside(["psql", "--version"], check=False).returncode:
        print("Installing PostgreSQL inside the lab container...")
        inside(["plesk", "installer", "--select-release-current", "--install-component", "postgresql"], label="PostgreSQL installation")
    marker = STATE / "postgres-admin-configured"
    container_id = execute(["docker", "inspect", "--format", "{{.Id}}", CONTAINER]).stdout.strip()
    if not marker.exists() or marker.read_text() != container_id:
        plesk(["database-server", "--update-server", "localhost:5432", "-type", "postgresql", "-admin", "postgres", "-passwd", ""], password=values["postgres_admin"])
        marker.write_text(container_id)
        marker.chmod(0o600)
    for driver, name, owner, secret, server in (
        ("postgresql", "tabularis_shop_pg", "shop_pg_owner", "pg_owner", "localhost:5432"),
        ("mysql", "tabularis_shop_mysql", "shop_mysql_owner", "mysql_owner", "localhost:3306"),
    ):
        if panel_query(f"SELECT count(*) FROM data_bases WHERE name='{name}'") == "0":
            plesk(["database", "--create", name, "-domain", DOMAIN, "-type", driver])
        plesk(["database", "--assign-to-domain", name, "-domain", DOMAIN, "-type", driver, "-server", server])
        if panel_query(f"SELECT count(*) FROM db_users WHERE login='{owner}'") == "0":
            plesk(["database", "--create-dbuser", owner, "-passwd", "", "-domain", DOMAIN, "-server", server, "-database", name], password=values[secret])
        if driver == "postgresql":
            shell = 'read -r PGPASSWORD; export PGPASSWORD; exec psql -X -A -t -h 127.0.0.1 -U "$1" -d "$2" -v ON_ERROR_STOP=1'
            query = "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name='customers';"
        else:
            shell = 'read -r MYSQL_PWD; export MYSQL_PWD; exec mariadb --default-character-set=utf8mb4 -N -h 127.0.0.1 -u "$1" "$2"'
            query = "SELECT count(*) FROM information_schema.tables WHERE table_schema=database() AND table_name='customers';"
        arguments = ["sh", "-c", shell, "sh", owner, name]
        present = inside(arguments, input_text=values[secret] + "\n" + query).stdout.strip()
        if present == "0":
            inside(arguments, input_text=values[secret] + "\n" + (HERE / f"{driver}-sample.sql").read_text(), label=f"{driver} sample data")
        print(f"Ready: {driver} database {name}, application user {owner}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap-only", action="store_true")
    arguments = parser.parse_args()
    validate_domain(DOMAIN)
    assert_lab()
    values = credentials()
    bootstrap(values)
    if not arguments.bootstrap_only:
        create_fixture_accounts(values)
        seed_databases(values)
        print("Ready: admin, customer tabularis-lab, allowed dbuser@example.test, denied nodbuser@example.test")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError) as error:
        raise SystemExit(str(error)) from None
