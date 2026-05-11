"""``wb-cli mqtt`` — raw MQTT read / write / list."""

from __future__ import annotations

import argparse

from wb_cli.errors import ExitCode, WbCliError
from wb_cli.plugin import BasePlugin


class MqttPlugin(BasePlugin):
    name = "mqtt"
    help = "raw MQTT: read retained, write, list topics"

    def register(self, subparsers: argparse._SubParsersAction) -> None:
        parser = subparsers.add_parser(
            self.name,
            help=self.help,
            description="Low-level MQTT operations.",
        )
        sub = parser.add_subparsers(dest="subcmd", metavar="<action>")

        p = sub.add_parser("read", help="read retained value from a topic")
        p.add_argument("topic", help="MQTT topic")
        p.add_argument("--timeout", type=float, default=5.0)
        p.add_argument("-q", "--quiet", action="store_true")

        p = sub.add_parser("write", help="publish a value to a topic")
        p.add_argument("topic", help="MQTT topic")
        p.add_argument("payload", help="value to publish")
        p.add_argument("-r", "--retain", action="store_true")
        p.add_argument("-q", "--quiet", action="store_true")

        p = sub.add_parser("list", help="list retained topics matching a pattern")
        p.add_argument("topic", nargs="?", default="#", help="topic filter (default: #)")
        p.add_argument("--timeout", type=float, default=5.0)
        p.add_argument("-q", "--quiet", action="store_true")

    def dispatch(self, ctx) -> dict:
        subcmd = ctx.args.subcmd
        if subcmd == "read":
            return self._read(ctx)
        if subcmd == "write":
            return self._write(ctx)
        if subcmd == "list":
            return self._list(ctx)
        return {}

    def _read(self, ctx) -> dict:
        topic = ctx.args.topic
        if "+" in topic or "#" in topic:
            raise WbCliError(
                code="MQTT_INVALID_TOPIC",
                message=f"'mqtt read' needs a concrete topic; use 'mqtt list' for wildcards: '{topic}'",
                details={"topic": topic},
                exit_code=ExitCode.USAGE,
            )
        msgs = ctx.mqtt.subscribe(topic, timeout=ctx.args.timeout)
        if not msgs:
            raise WbCliError(
                code="MQTT_TIMEOUT",
                message=f"No retained value on '{topic}'",
                details={"topic": topic},
                exit_code=ExitCode.DOMAIN,
            )
        return {"topic": msgs[0][0], "payload": msgs[0][1]}

    def _write(self, ctx) -> dict:
        ctx.mqtt.publish(
            ctx.args.topic,
            ctx.args.payload,
            retain=ctx.args.retain,
        )
        return {"topic": ctx.args.topic, "ok": True}

    def _list(self, ctx) -> dict:
        msgs = ctx.mqtt.subscribe(
            ctx.args.topic,
            timeout=ctx.args.timeout,
        )
        topics = [{"topic": t, "payload": p} for t, p in msgs]
        return {"topics": topics, "count": len(topics)}

    def render(self, result):
        # `mqtt read`: just print the payload.
        if "payload" in result and "topic" in result and "topics" not in result:
            return str(result["payload"])
        # `mqtt write`: confirm.
        if "ok" in result:
            return f"ok  {result.get('topic', '')}"
        # `mqtt list`: line per topic.
        if "topics" in result:
            return "\n".join(f"{t['topic']}\t{t['payload']}" for t in result["topics"])
        return None


PLUGIN = MqttPlugin()
