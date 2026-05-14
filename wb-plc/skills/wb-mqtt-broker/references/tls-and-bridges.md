# MQTT TLS and bridges

## TLS on port 8883

### Certificates

A self-signed CA + server certificate for home tasks. For production prefer Let's Encrypt (via certbot/acme.sh) with a public domain.

```bash
# self-signed CA + server cert (one-time)
ssh root@<HOST> 'mkdir -p /etc/mosquitto/certs && cd /etc/mosquitto/certs && \
  openssl genrsa -out ca.key 2048 && \
  openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 -out ca.crt -subj "/CN=WB-MQTT-CA" && \
  openssl genrsa -out server.key 2048 && \
  openssl req -new -key server.key -out server.csr -subj "/CN=wirenboard-<SN>.local" && \
  openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days 3650 -sha256 && \
  chown mosquitto:mosquitto *.key *.crt && chmod 0640 *.key'
```

### TLS listener

```bash
ssh root@<HOST> 'cat >> /etc/mosquitto/conf.d/10listeners.conf' <<'EOF'

listener 8883
allow_anonymous false
acl_file /etc/mosquitto/acl/default.conf
password_file /etc/mosquitto/passwd/default.conf
cafile /etc/mosquitto/certs/ca.crt
certfile /etc/mosquitto/certs/server.crt
keyfile /etc/mosquitto/certs/server.key
EOF
ssh root@<HOST> 'systemctl restart mosquitto'
```

### TLS test

```bash
ssh root@<HOST> "mosquitto_sub -h localhost -p 8883 --cafile /etc/mosquitto/certs/ca.crt -u <u> -P <p> -t test -C 1 -W 5"
```

From an external host — distribute `ca.crt` to the client, connect to `wirenboard-<SN>.local:8883`. Self-signed without `--cafile` — `tls_version mismatch`/`certificate verify failed`.

For Let's Encrypt — `cafile` not needed (system CA), `certfile`/`keyfile` point to the certbot paths.

## Bridges — bridges to other brokers

A bridge is a mode where mosquitto itself connects to another broker and copies selected topics back and forth. Typical cases: replication to Home Assistant, copy to cloud, backup broker.

### Example: bridge to Home Assistant

`/etc/mosquitto/conf.d/20bridges.conf`:

```bash
ssh root@<HOST> 'cat > /etc/mosquitto/conf.d/20bridges.conf' <<'EOF'
connection ha-bridge
address ha.local:1883
topic /devices/# out 0 wb/A25NDEMJ/
topic ha/wb/cmd/+ in 0
remote_username <ha_mqtt_user>
remote_password <ha_mqtt_password>
keepalive_interval 60
restart_timeout 10
notifications true
notifications_topic wb/A25NDEMJ/bridge/state
cleansession false
try_private false
EOF
ssh root@<HOST> 'systemctl restart mosquitto'
```

Topic parameter: `<pattern> <direction> <qos> <local-prefix> <remote-prefix>`.

- `out` — publish there (outbound), `in` — pull here, `both` — both directions.
- `wb/A25NDEMJ/` — prefix on the remote side (the topics `wb/A25NDEMJ/devices/...` will be visible there).

`wb-notifications` creates `wb/A25NDEMJ/bridge/state` with `online`/`offline` — convenient for monitoring connectivity.

`cleansession false` is important: on disconnect, messages with QoS≥1 accumulate and are delivered after recovery.

### Bridge with TLS

Add to the connection block:

```
bridge_cafile /etc/mosquitto/certs/ha-ca.crt
bridge_certfile /etc/mosquitto/certs/wb-client.crt
bridge_keyfile /etc/mosquitto/certs/wb-client.key
bridge_insecure false
```

`bridge_insecure true` disables hostname verification — only for debugging.
