import axios from "axios";

import type {
  Alert,
  AlertListOut,
  AlertRule,
  AlertRuleCreateIn,
  TelegramProbeOut,
} from "../types/alerts";

/**
 * Cliente del modulo de alertas.
 *
 * Mismo patron que `backtestsApi`: `baseURL` relativo que resuelve el proxy de
 * Vite y un `timeout` de 30 s. El `probe` es la excepción que **no** llega a
 * 30 s: envía un mensaje de verdad por la red de Telegram, y un timeout corto
 * daría un error falso justo en la operación que se usa para diagnosticar.
 */
const apiClient = axios.create({
  baseURL: "/api/v1/alerts",
  timeout: 30000,
});

export async function getAlertRules(soloActivas = false): Promise<AlertRule[]> {
  const { data } = await apiClient.get<AlertRule[]>("/rules", {
    params: soloActivas ? { solo_activas: true } : {},
  });
  return data;
}

/**
 * Crea una regla. **Nunca falla por el veredicto del respaldo**: un
 * `descartada` nace con su etiqueta y el aviso sale con su icono.
 *
 * Lo que sí es 409 es lo que no tiene arreglo avisando: una dirección opuesta a
 * la del catálogo, un patrón inexistente, un nombre vacío.
 */
export async function createAlertRule(cuerpo: AlertRuleCreateIn): Promise<AlertRule> {
  const { data } = await apiClient.post<AlertRule>("/rules", cuerpo);
  return data;
}

/** Activa o desactiva. No toca la configuración: cambiarla es crear otra. */
export async function setAlertRuleEnabled(ruleId: string, enabled: boolean): Promise<AlertRule> {
  const { data } = await apiClient.patch<AlertRule>(`/rules/${ruleId}`, { enabled });
  return data;
}

export async function deleteAlertRule(ruleId: string): Promise<void> {
  await apiClient.delete(`/rules/${ruleId}`);
}

export async function getAlerts(page = 1, soloFallidas = false): Promise<AlertListOut> {
  const { data } = await apiClient.get<AlertListOut>("/", {
    params: { page, solo_fallidas: soloFallidas },
  });
  return data;
}

export async function getAlert(alertId: string): Promise<Alert> {
  const { data } = await apiClient.get<Alert>(`/${alertId}`);
  return data;
}

/** Reenvía una alerta fallida. Una `sent` o una `skipped` dan 409. */
export async function retryAlert(alertId: string): Promise<Alert> {
  const { data } = await apiClient.post<Alert>(`/${alertId}/retry`);
  return data;
}

/**
 * Prueba el canal y devuelve **cómo arreglarlo** si no funciona.
 *
 * Existe por una razón concreta: la causa número uno de «las alertas no me
 * llegan» es de configuración —un `/start` que no se mandó, un token mal
 * pegado— y descubrirlo esperando una detección real del mercado es esperar
 * horas para enterarse de un dedo que no se movió.
 */
export async function probeTelegram(): Promise<TelegramProbeOut> {
  const { data } = await apiClient.post<TelegramProbeOut>(
    "/telegram/probe",
    {},
    { timeout: 60000 },
  );
  return data;
}
