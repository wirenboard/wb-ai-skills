# MQTT authentication — passwords and ACL

## Passwords

### Create password file

```bash
ssh root@<HOST> 'mkdir -p /etc/mosquitto/passwd; chown mosquitto:mosquitto /etc/mosquitto/passwd'
ssh root@<HOST> 'mosquitto_passwd -c /etc/mosquitto/passwd/default.conf <username>'
# enter password: ****
ssh root@<HOST> 'chown mosquitto:mosquitto /etc/mosquitto/passwd/default.conf; chmod 0640 /etc/mosquitto/passwd/default.conf'
```

`-c` — create file (overwrites existing!). Without `-c` — add a user to an existing file. Delete user: `mosquitto_passwd -D /etc/mosquitto/passwd/default.conf <username>`.

### Configure listener to use passwords

In `/etc/mosquitto/conf.d/10listeners.conf` there's already an example. Edit to disable anonymous:

```bash
ssh root@<HOST> 'cat > /etc/mosquitto/conf.d/10listeners.conf' <<'EOF'
listener 1883
allow_anonymous false
acl_file /etc/mosquitto/acl/default.conf
password_file /etc/mosquitto/passwd/default.conf
EOF
ssh root@<HOST> 'systemctl restart mosquitto'
```

`per_listener_settings true` (in `00default_listener.conf`) is key: allows different `allow_anonymous` for different listeners. The internal socket stays anonymous, the external one requires a password.

### Test

```bash
ssh root@<HOST> "mosquitto_sub -h localhost -p 1883 -u <user> -P <pwd> -t '/devices/+/meta/name' -C 3 -W 3"
```

Without `-u`/`-P` should refuse (`Connection error: Connection Refused: not authorised.`).

## ACL — per-user permissions

ACL file — user permissions on topics:

```bash
ssh root@<HOST> 'cat > /etc/mosquitto/acl/default.conf' <<'EOF'
# Default — anonymous deny
topic deny #

# user "admin" — full access
user admin
topic readwrite #

# user "frontend" — read /devices/ only, write /devices/+/controls/+/on
user frontend
topic read /devices/#
topic write /devices/+/controls/+/on

# user "external_app" — only its own namespace
user external_app
topic readwrite app/external_app/#
EOF
ssh root@<HOST> 'systemctl reload mosquitto'   # ACLs reload (no restart required)
```

Each message is checked against the ACL before publishing. **Internal WB services via the Unix socket are not affected by the ACL** — they have their own section in `00default_listener.conf` (`allow_anonymous true`, no acl_file).
