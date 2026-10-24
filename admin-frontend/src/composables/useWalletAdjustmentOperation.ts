import { shallowRef } from 'vue'

export interface WalletAdjustmentIntent {
  userId: number
  action: 'deposit' | 'withdraw'
  amount: number
  note: string
}

export function useWalletAdjustmentOperation() {
  const pending = shallowRef<{ signature: string; id: string } | null>(null)

  function operationId(intent: WalletAdjustmentIntent): string {
    const signature = JSON.stringify(intent)
    if (pending.value?.signature === signature) return pending.value.id
    const id = crypto.randomUUID()
    pending.value = { signature, id }
    return id
  }

  function complete(id: string) {
    if (pending.value?.id === id) pending.value = null
  }

  return { operationId, complete }
}
