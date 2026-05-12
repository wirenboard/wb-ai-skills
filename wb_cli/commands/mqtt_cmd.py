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
            description=(
                "Direct access to the MQTT broker. Prefer `devices` for /devices/<id>/\n"
                "topics — it understands metadata and refuses bad writes. Use `mqtt`\n"
                "for everything else: /rpc/, /scenarios/, custom topics."
            ),
            epilog=(
                "Examples:\n"
                "  wb-cli mqtt read  /devices/wb-mr6c_2/controls/K1\n"
                "  wb-cli mqtt write /devices/wb-mr6c_2/controls/K1/on 1\n"
                "  wb-cli mqtt write -r /my-app/config '{\"foo\":1}'   # retained\n"
                "  wb-cli mqtt list '/devices/+/meta/name'             # one wildcard level\n"
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        sub = parser.add_subparsers(dest="subcmd", metavar="<action>")

        p = sub.add_parser(
            "read",
            help="read the retained value of one topic",
            description=(
                "Print the retained payload of <topic>. " "Wildcards (+, #) are rejected — use `mqtt list`."
            ),
        )
        p.add_argument("topic", help="exact MQTT topic, no wildcards")
        p.add_argument("--timeout", type=float, default=5.0, help="seconds to wait (default: 5)")

        p = sub.add_parser(
            "write",
            help="publish a value to a topic (use -r for retained)",
            description=(
                "Publish one message. Without -r the message is volatile — fine "
                "for command topics like .../on."
            ),
        )
        p.add_argument("topic", help="MQTT topic to publish to")
        p.add_argument("payload", help="payload string")
        p.add_argument("-r", "--retain", action="store_true", help="set the retain flag")

        p = sub.add_parser(
            "list",
            help="list retained topics matching a wildcard pattern",
            description="Subscribe to <pattern> and dump every retained topic with its payload.",
        )
        p.add_argument(
            "topic",
            nargs="?",
            default="#",
            help="MQTT wildcard pattern (default: # — everything; can be heavy)",
        )
        p.add_argument("--timeout", type=float, default=5.0, help="max seconds to wait (default: 5)")

        p = sub.add_parser(
            "sub",
            help="subscribe and print messages (retained + live)",
            description=(
                "Subscribe to <topic> and print every message that arrives. "
                "Captures both retained and live (non-retained) messages. "
                "Use --count to stop after N messages, --timeout to limit wait time."
            ),
        )
        p.add_argument("topic", help="MQTT topic or wildcard pattern")
        p.add_argument(
            "-C",
            "--count",
            type=int,
            default=None,
            metavar="N",
            help="stop after N messages",
        )
        p.add_argument("--timeout", type=float, default=5.0, help="max seconds to wait (default: 5)")

    def dispatch(self, ctx) -> dict:
        subcmd = ctx.args.subcmd
        if subcmd == "read":
            return self._read(ctx)
        if subcmd == "write":
            return self._write(ctx)
        if subcmd == "list":
            return self._list(ctx)
        if subcmd == "sub":
            return self._sub(ctx)
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
        msgs = ctx.mqtt.subscribe(ctx.args.topic, timeout=ctx.args.timeout)
        messages = [{"topic": t, "payload": p} for t, p in msgs]
        return {"messages": messages, "count": len(messages)}

    def _sub(self, ctx) -> dict:
        msgs = ctx.mqtt.subscribe_live(
            ctx.args.topic,
            count=ctx.args.count,
            timeout=ctx.args.timeout,
        )
        messages = [{"topic": t, "payload": p} for t, p in msgs]
        return {"messages": messages, "count": len(messages)}

    def render(self, result):
        # `mqtt read`: just print the payload.
        if "payload" in result and "topic" in result and "messages" not in result:
            return str(result["payload"])
        # `mqtt write`: confirm.
        if "ok" in result:
            return f"ok  {result.get('topic', '')}"
        # `mqtt list`: line per topic.
        if "messages" in result:
            return "\n".join(f"{m['topic']}\t{m['payload']}" for m in result["messages"])
        return None


PLUGIN = MqttPlugin()
