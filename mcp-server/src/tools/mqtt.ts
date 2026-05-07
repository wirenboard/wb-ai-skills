import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { z } from 'zod'
import { type Ctx, resolveController, text, SN } from '../helpers.ts'

export function registerMqttTools(server: McpServer, ctx: Ctx) {
  server.registerTool('wb_mqtt_read', {
    description: 'Read a retained MQTT topic',
    inputSchema: z.object({
      sn: SN,
      topic: z.string().describe('MQTT topic (e.g. /devices/wb-mr6c_7/controls/K1)'),
    }),
  }, async ({ sn, topic }) => {
    return text(await ctx.ssh.mqttRead(resolveController(ctx, sn), topic, 5))
  })

  server.registerTool('wb_mqtt_write', {
    description: 'Write a value to an MQTT topic. Can be used for arbitrary non-WB topics (zigbee2mqtt/.../set, tasmota/.../cmnd/POWER, etc.) — specify retain/qos as needed. For WB controls, publish to `<topic>/on` (the value is applied by the driver and published back with retain).',
    inputSchema: z.object({
      sn: SN,
      topic: z.string().describe('MQTT topic'),
      value: z.string().describe('Value'),
      retain: z.boolean().optional().default(false).describe('Publish with retain (stick as a retained message). Default false.'),
      qos: z.union([z.literal(0), z.literal(1), z.literal(2)]).optional().default(0).describe('QoS level: 0 (fire-and-forget), 1 (at-least-once), 2 (exactly-once). Default 0.'),
    }),
  }, async ({ sn, topic, value, retain, qos }) => {
    await ctx.ssh.mqttPublish(resolveController(ctx, sn), topic, value, { retain, qos })
    return text({ ok: true, topic, value, retain, qos })
  })

  server.registerTool('wb_mqtt_list', {
    description: 'List MQTT topics matching a prefix',
    inputSchema: z.object({
      sn: SN,
      prefix: z.string().default('#').describe('Prefix (e.g. /devices/+/meta/name)'),
      timeout: z.number().optional().default(3).describe('Collection timeout in seconds'),
    }),
  }, async ({ sn, prefix, timeout }) => {
    return text(await ctx.ssh.mqttListTopics(resolveController(ctx, sn), prefix, timeout))
  })

  server.registerTool('wb_mqtt_rpc', {
    description: 'Invoke an MQTT RPC (wb-mqtt-serial, confed, wbrules, db_logger, etc.)',
    inputSchema: z.object({
      sn: SN,
      driver: z.string().describe('Driver (wb-mqtt-serial, confed, wbrules, db_logger)'),
      service: z.string().describe('Service (config, device, Editor, port, ports, templates, history)'),
      method: z.string().describe('Method (Load, Save, LoadConfig, Scan, Probe, List, get_values)'),
      params: z.record(z.unknown()).default({}).describe('RPC parameters'),
      timeout: z.number().optional().default(10).describe('Timeout in seconds'),
    }),
  }, async ({ sn, driver, service, method, params, timeout }) => {
    return text(await ctx.ssh.mqttRpc(resolveController(ctx, sn), driver, service, method, params, timeout))
  })
}
