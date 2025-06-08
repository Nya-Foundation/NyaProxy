<script setup lang="ts">
import { getAuth } from '@/api/dashboardApi';
import { useAuthStore } from '@/stores/modules/auth';
import type { AuthCookie } from '@/types/auth';
import { setToken } from '@/utils/auth';
import type { FormInstance, FormRules } from 'element-plus';
import { ElMessage } from 'element-plus';
import { onMounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';

const authState = useAuthStore();
const router = useRouter();

const formRef = ref<FormInstance>();
const pwd = ref<AuthCookie>({
  key: ''
});

const rules = reactive<FormRules<AuthCookie>>({
  key: [
    {
      required: true,
      message: 'Please enter API Key',
      trigger: 'blur'
    }
  ]
});

const onSubmit = async (formEl: FormInstance | undefined) => {
  if (!formEl) return;
  await formEl.validate(async (valid, fields) => {
    if (valid) {
      try {
        setToken(pwd.value.key);
        await getAuth();
        ElMessage.success('Login Success');
        authState.login(pwd.value.key);
        if (router.currentRoute.value.query.return_path) {
          router.push(router.currentRoute.value.query.return_path as string);
        } else {
          router.push('/');
        }
      } catch (err) {
        console.log(err);
        pwd.value.key = '';
        ElMessage.error('Login Failed, please try again');
      }
    } else {
      console.log('error: ', fields);
    }
  });
};

onMounted(async () => {
  try {
    await getAuth();
    setToken('');
    authState.login('');
    router.push('/');
  } catch (err) {
    console.log(err);
  }
});
</script>

<template>
  <div class="login-page h-screen font-sans bg-cover">
    <div class="container mx-auto h-full flex flex-1 justify-center items-center">
      <div class="relative mx-10 sm:max-w-sm w-full">
        <div
          class="card bg-blue-400 shadow-lg w-full h-full rounded-3xl absolute transform -rotate-6"
        ></div>
        <div
          class="card bg-red-400 shadow-lg w-full h-full rounded-3xl absolute transform rotate-6"
        ></div>
        <div class="relative p-4 w-auto rounded-3xl bg-gray-100 shadow-md">
          <div class="flex justify-center">
            <img src="@/assets/images/logo.svg" alt="logo" class="w-1/5" />
          </div>
          <label for="" class="block mt-3 text-2xl text-gray-700 text-center font-semibold">
            NyaProxy
          </label>
          <el-form
            class="w-full max-w-sm mx-auto my-5"
            ref="formRef"
            :model="pwd"
            :rules="rules"
            label-width="auto"
            :hide-required-asterisk="true"
          >
            <el-form-item label="API Key" label-position="top" prop="key">
              <el-input
                v-model="pwd.key"
                type="password"
                autocomplete="off"
                show-password
                size="large"
                autofocus
              />
            </el-form-item>
            <el-form-item>
              <el-button size="large" type="primary" round @click="onSubmit(formRef)"
                >Login</el-button
              >
            </el-form-item>
          </el-form>
          <div class="login-card-footer">
            <span>
              Powered by
              <el-link
                type="primary"
                href="https://github.com/Nya-Foundation/NyaProxy"
                target="_blank"
                >NyaProxy</el-link
              >
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.login-page {
  box-sizing: content-box;
  background: url('@/assets/images/background.webp');
  background-repeat: no-repeat;
  background-size: cover;
}

.el-button {
  width: 100%;
  margin-top: 10px;
  :deep(span) {
    font-size: 16px;
  }
}

.login-card-footer {
  display: flex;
  justify-content: center;
  align-items: center;
  margin-bottom: 12px;
}
</style>
