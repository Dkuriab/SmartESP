// Известные аккаунты каналов для «Связей»: пользователи Telegram-бота из его настройки
// TELEGRAM_USERS («user_id=имя;…»), которую интерфейс уже загрузил (GET /connectors).
import type { CoreState } from '../../state/model'

export const TELEGRAM = 'telegram'
const BOT_ID = 'telegram' // id клиента «Telegram-бот» в connectors
const USERS_KEY = 'TELEGRAM_USERS'

/** Аккаунт канала с именем, под которым его знает канал. */
export type KnownAccount = { channel: string; account: string; name: string }

/** «111=Аня;222=Боб» → [{account: '111', name: 'Аня'}, …]; записи без «=» или без id пропускаются. */
export function parsePairs(value: string): Array<{ account: string; name: string }> {
  return value.split(';').flatMap((item) => {
    const at = item.indexOf('=')
    const account = item.slice(0, at).trim()
    return at < 0 || !account ? [] : [{ account, name: item.slice(at + 1).trim() }]
  })
}

/** Пользователи Telegram-бота из его настроек (бот не настроен — пусто). */
export function telegramAccounts(state: CoreState): KnownAccount[] {
  const bot = state.connectors?.find((c) => c.id === BOT_ID)
  const users = bot?.settings?.find((s) => s.key === USERS_KEY)?.value ?? ''
  return parsePairs(users).map((u) => ({ channel: TELEGRAM, ...u }))
}
