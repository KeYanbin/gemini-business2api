<template>
  <div class="min-h-screen px-4">
    <div class="flex min-h-screen items-center justify-center">
      <div class="w-full max-w-md rounded-[2.5rem] border border-border bg-card p-10 shadow-2xl shadow-black/10">
        <div class="text-center">
          <h1 class="text-3xl font-semibold text-foreground">Gemini Business 2API</h1>
          <p class="mt-2 text-sm text-muted-foreground">管理员登录</p>
        </div>

        <form @submit.prevent="handleLogin" class="mt-8 space-y-6">
          <div class="space-y-2">
            <label for="password" class="block text-sm font-medium text-foreground">
              管理员密钥
            </label>
            <input
              id="password"
              v-model="password"
              type="password"
              required
              class="w-full rounded-2xl border border-input bg-background px-4 py-3 text-sm
                     focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent
                     transition-all"
              placeholder="请输入管理员密钥"
              :disabled="isLoading"
            />
          </div>

          <div v-if="errorMessage" class="rounded-2xl bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {{ errorMessage }}
          </div>

          <button
            type="submit"
            :disabled="isLoading || !password"
            class="w-full rounded-2xl bg-primary py-3 text-sm font-medium text-primary-foreground
                   transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {{ isLoading ? '登录中...' : '登录' }}
          </button>
        </form>

        <div class="mt-8 flex items-center justify-center text-xs text-muted-foreground">
          <span>Powered by Gemini Business API</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores'

const router = useRouter()
const authStore = useAuthStore()

const password = ref('')
const errorMessage = ref('')
const isLoading = ref(false)

async function handleLogin() {
  if (!password.value) return

  errorMessage.value = ''
  isLoading.value = true

  try {
    await authStore.login(password.value)
    router.push({ name: 'dashboard' })
  } catch (error: any) {
    errorMessage.value = error.message || '登录失败，请检查密钥。'
  } finally {
    isLoading.value = false
  }
}
</script>
