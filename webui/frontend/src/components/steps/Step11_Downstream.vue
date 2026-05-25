<template>
  <section class="step-fade-in">
    <div class="term-divider" data-tail="──────────">步骤 11: 下游推送</div>
    <h2 class="step-h">$&nbsp;下游推送 (全部可选)<span class="term-cursor"></span></h2>

    <div class="term-divider" style="margin-top:8px">gpt-team</div>
    <TermToggle v-model="ts.enabled">启用 gpt-team</TermToggle>
    <div v-if="ts.enabled" class="form-stack" style="margin-top:12px">
      <TermField v-model="ts.base_url" label="Base URL · base_url" />
      <TermField v-model="ts.username" label="用户名 · username" />
      <TermField v-model="ts.password" label="密码 · password" type="password" />
      <div class="step-actions">
        <TermBtn :loading="tsLoading" @click="testTs">登录测试</TermBtn>
      </div>
      <div v-if="tsResult" class="result-block" :class="`result--${tsResult.status}`">
        <div class="result-head">
          <span class="result-icon">{{ icon(tsResult.status) }}</span>
          <span>{{ tsResult.message }}</span>
        </div>
      </div>
    </div>

    <div class="term-divider" style="margin-top:20px">CPA</div>
    <TermToggle v-model="cpa.enabled">启用 CPA</TermToggle>
    <div v-if="cpa.enabled" class="form-stack" style="margin-top:12px">
      <TermField v-model="cpa.base_url" label="Base URL · base_url" />
      <TermField v-model="cpa.admin_key" label="Admin Key · admin_key" type="password" />
      <div class="step-actions">
        <TermBtn :loading="cpaLoading" @click="testCpa">健康检查</TermBtn>
      </div>
      <div v-if="cpaResult" class="result-block" :class="`result--${cpaResult.status}`">
        <div class="result-head">
          <span class="result-icon">{{ icon(cpaResult.status) }}</span>
          <span>{{ cpaResult.message }}</span>
        </div>
      </div>
    </div>

    <div class="term-divider" style="margin-top:20px">散户面板 (cpa_autofill)</div>
    <TermToggle v-model="af.enabled">启用散户面板推送</TermToggle>
    <div v-if="af.enabled" class="form-stack" style="margin-top:12px">
      <TermField v-model="af.base_url" label="Base URL · base_url (例: https://autofill.lukyface.com)" />
      <TermField v-model="af.api_token" label="API Token · /supplier 面板里轮换出来的 Bearer token" type="password" />
      <p style="font-size:12px; color:#7a7363; margin:4px 0 0">挂单价 (元/号) 在每次推送时弹窗输入,不在这里预设。</p>
    </div>

    <div class="term-divider" style="margin-top:20px">Sub2API</div>
    <TermToggle v-model="sub.enabled">启用 Sub2API 推送</TermToggle>
    <div v-if="sub.enabled" class="form-stack" style="margin-top:12px">
      <TermField v-model="sub.base_url" label="Base URL · base_url (例: https://sub2api.example.com)" />
      <TermField v-model="sub.admin_api_key" label="Admin API Key · admin_api_key" type="password" />
      <TermField v-model="sub.group_ids" label="Group IDs · group_ids (可选,逗号分隔)" />
      <TermField v-model="sub.concurrency" label="并发 · concurrency (可选)" type="number" />
      <TermField v-model="sub.priority" label="优先级 · priority (可选)" type="number" />
      <TermField v-model="sub.oauth_client_id" label="Codex OAuth Client ID · oauth_client_id (可选)" />
      <TermToggle v-model="sub.update_existing">导入时更新已存在账号</TermToggle>
      <div class="step-actions">
        <TermBtn :loading="subLoading" @click="testSub2Api">连接测试</TermBtn>
      </div>
      <div v-if="subResult" class="result-block" :class="`result--${subResult.status}`">
        <div class="result-head">
          <span class="result-icon">{{ icon(subResult.status) }}</span>
          <span>{{ subResult.message }}</span>
        </div>
      </div>
      <p style="font-size:12px; color:#7a7363; margin:4px 0 0">推送前会优先用 refresh_token 换新 access_token/id_token,再导入 Sub2API。</p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from "vue";
import { useWizardStore } from "../../stores/wizard";
import type { PreflightResult } from "../../api/client";
import TermField from "../term/TermField.vue";
import TermBtn from "../term/TermBtn.vue";
import TermToggle from "../term/TermToggle.vue";

const store = useWizardStore();
const tsInit = store.answers.team_system ?? {};
const cpaInit = store.answers.cpa ?? {};
const afInit = store.answers.cpa_autofill ?? {};
const subInit = store.answers.sub2api ?? {};

// 开关默认关闭（不读 init.enabled），但其余字段保留 source 同步的值
// 这样用户启用 toggle 时直接看到预填的 url/凭据
const ts = ref({
  enabled: false,
  base_url: tsInit.base_url ?? "http://127.0.0.1:3000",
  username: tsInit.username ?? "admin",
  password: tsInit.password ?? "",
});
const cpa = ref({
  enabled: false,
  base_url: cpaInit.base_url ?? "",
  admin_key: cpaInit.admin_key ?? "",
});
const af = ref({
  enabled: false,
  base_url: afInit.base_url ?? "https://autofill.lukyface.com",
  api_token: afInit.api_token ?? "",
});
const sub = ref({
  enabled: false,
  base_url: subInit.base_url ?? "",
  admin_api_key: subInit.admin_api_key ?? "",
  group_ids: subInit.group_ids ?? "",
  concurrency: subInit.concurrency ?? "",
  priority: subInit.priority ?? "",
  update_existing: subInit.update_existing ?? true,
  oauth_client_id: subInit.oauth_client_id ?? "",
});

// 立即同步到 store 覆盖可能从 source 同步过来的 enabled=true，
// 否则 UI 显示关但 wizard state / 导出仍会写 enabled=true
onMounted(() => {
  store.setAnswer("team_system", {});
  store.setAnswer("cpa", {});
  store.setAnswer("cpa_autofill", {});
  store.setAnswer("sub2api", {});
  store.saveToServer();
});
const tsLoading = ref(false);
const cpaLoading = ref(false);
const subLoading = ref(false);
const tsResult = ref<PreflightResult | null>(null);
const cpaResult = ref<PreflightResult | null>(null);
const subResult = ref<PreflightResult | null>(null);

async function testTs() {
  tsLoading.value = true;
  try {
    tsResult.value = await store.runPreflight("team_system", {
      base_url: ts.value.base_url,
      username: ts.value.username,
      password: ts.value.password,
    });
  } finally { tsLoading.value = false; }
}
async function testCpa() {
  cpaLoading.value = true;
  try {
    cpaResult.value = await store.runPreflight("cpa", {
      base_url: cpa.value.base_url,
      admin_key: cpa.value.admin_key,
    });
  } finally { cpaLoading.value = false; }
}
async function testSub2Api() {
  subLoading.value = true;
  try {
    subResult.value = await store.runPreflight("sub2api", {
      base_url: sub.value.base_url,
      admin_api_key: sub.value.admin_api_key,
    });
  } finally { subLoading.value = false; }
}
watch([ts, cpa, af, sub], () => {
  store.setAnswer("team_system", ts.value.enabled ? ts.value : {});
  store.setAnswer("cpa", cpa.value.enabled ? cpa.value : {});
  store.setAnswer("cpa_autofill", af.value.enabled ? af.value : {});
  store.setAnswer("sub2api", sub.value.enabled ? sub.value : {});
  store.saveToServer();
}, { deep: true });

function icon(s: string) {
  return s === "ok" ? "✓" : s === "fail" ? "✗" : s === "warn" ? "▲" : "○";
}
</script>
