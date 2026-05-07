import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { z } from 'zod'
import { type Ctx, resolveController, text, SN } from '../helpers.ts'

export function registerMqttTools(server: McpServer, ctx: Ctx) {
  server.registerTool('wb_mqtt_read', {
    description: 'Прочитать retained MQTT-топик',
    inputSchema: z.object({
      sn: SN,
      topic: z.string().describe('MQTT-топик (например /devices/wb-mr6c_7/controls/K1)'),
    }),
  }, async ({ sn, topic }) => {
    return text(await ctx.ssh.mqttRead(resolveController(ctx, sn), topic, 5))
  })

  server.registerTool('wb_mqtt_write', {
    description: 'Записать значение в MQTT-топик. Можно использовать для произвольных не-WB топиков (zigbee2mqtt/.../set, tasmota/.../cmnd/POWER и т.п.) — указав retain/qos при необходимости. Для WB-контролов публикуй в `<topic>/on` (значение применится драйвером и опубликуется обратно с retain).',
    inputSchema: z.object({
      sn: SN,
      topic: z.string().describe('MQTT-топик'),
      value: z.string().describe('Значение'),
      retain: z.boolean().optional().default(false).describe('Опубликовать с retain (приклеить как retained-сообщение). По умолчанию false.'),
      qos: z.union([z.literal(0), z.literal(1), z.literal(2)]).optional().default(0).describe('QoS уровень: 0 (fire-and-forget), 1 (at-least-once), 2 (exactly-once). По умолчанию 0.'),
    }),
  }, async ({ sn, topic, value, retain, qos }) => {
    await ctx.ssh.mqttPublish(resolveController(ctx, sn), topic, value, { retain, qos })
    return text({ ok: true, topic, value, retain, qos })
  })

  server.registerTool('wb_mqtt_list', {
    description: 'Получить список MQTT-топиков по префиксу',
    inputSchema: z.object({
      sn: SN,
      prefix: z.string().default('#').describe('Префикс (например /devices/+/meta/name)'),
      timeout: z.number().optional().default(3).describe('Таймаут сбора в секундах'),
    }),
  }, async ({ sn, prefix, timeout }) => {
    return text(await ctx.ssh.mqttListTopics(resolveController(ctx, sn), prefix, timeout))
  })

  server.registerTool('wb_mqtt_rpc', {
    description: 'Вызвать MQTT RPC (wb-mqtt-serial, confed, wbrules, db_logger и др.)',
    inputSchema: z.object({
      sn: SN,
      driver: z.string().describe('Драйвер (wb-mqtt-serial, confed, wbrules, db_logger)'),
      service: z.string().describe('Сервис (config, device, Editor, port, ports, templates, history)'),
      method: z.string().describe('Метод (Load, Save, LoadConfig, Scan, Probe, List, get_values)'),
      params: z.record(z.unknown()).default({}).describe('Параметры RPC'),
      timeout: z.number().optional().default(10).describe('Таймаут в секундах'),
    }),
  }, async ({ sn, driver, service, method, params, timeout }) => {
    return text(await ctx.ssh.mqttRpc(resolveController(ctx, sn), driver, service, method, params, timeout))
  })
}
