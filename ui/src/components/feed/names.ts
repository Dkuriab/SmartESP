// Имена исполнителей для ленты: по id из настроек, неизвестный — сам id.

/** Исполнитель в той мере, в какой он нужен ленте. */
export type ExecutorName = { id: string; name: string }

/** Имя исполнителя id; нет в списке или без имени — id. */
export function executorName(executors: ExecutorName[], id: string): string {
  return executors.find((e) => e.id === id)?.name || id
}
