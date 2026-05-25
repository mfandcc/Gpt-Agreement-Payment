<template>
  <section class="step-fade-in">
    <div class="term-divider" data-tail="──────────">步骤 14: 接码平台</div>
    <h2 class="step-h">$&nbsp;SMSBower add-phone 接码<span class="term-cursor"></span></h2>
    <p class="step-sub">
      仅用于 Codex OAuth 重登拿 RT 时遇到 <code>add-phone</code> 且页面没有 Skip 的情况。默认关闭；打开后会购买号码、填写手机号、轮询短信验证码并提交。号码会进入本地号池：25 分钟内复用，同一号码最多接 3 次验证码，不会主动取消或删除 SMSBower 激活。
    </p>

    <div class="form-stack">
      <TermToggle v-model="form.enabled">启用 SMSBower 自动接码</TermToggle>
      <TermField v-model="form.api_key" label="API Key" type="password" placeholder="SMSBower API key" />
      <TermField v-model="form.api_url" label="API URL" placeholder="https://smsbower.online/stubs/handler_api.php" />
      <div class="grid-2">
        <TermField v-model="form.service" label="服务码 · service" placeholder="dr" />
        <TermField v-model="form.country" label="国家编号 · country" placeholder="0" />
      </div>
      <div class="grid-2">
        <TermField v-model="form.operator" label="运营商 · operator" placeholder="any / 留空" />
        <TermField v-model="form.max_price" label="最高价 · max_price" placeholder="留空不限" />
      </div>
      <div class="grid-3">
        <TermField v-model="form.phone_prefix" label="号码前缀" placeholder="+" />
        <TermField v-model.number="form.timeout_s" label="验证码超时秒" type="number" />
        <TermField v-model.number="form.poll_interval_s" label="轮询间隔秒" type="number" />
      </div>
      <div class="grid-3">
        <TermField v-model.number="form.pool_ttl_s" label="号池有效秒" type="number" placeholder="1500" />
        <TermField v-model.number="form.pool_max_uses" label="每号接码次数" type="number" placeholder="3" />
        <TermField v-model="form.pool_path" label="号池文件路径" placeholder="留空默认 output/sms_bower_pool.json" />
      </div>
    </div>

    <div class="result-block result--warn" style="margin-top:16px">
      <div class="result-head">
        <span class="result-icon">▲</span>
        <span>服务码和国家编号以 SMSBower 后台实时库存为准；如果 OpenAI 页面要求选择国家区号，优先选匹配 country 的号码。号池只记录和复用号码，不会调用取消/删除操作。</span>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, watch } from "vue";
import { useWizardStore } from "../../stores/wizard";
import TermField from "../term/TermField.vue";
import TermToggle from "../term/TermToggle.vue";

const store = useWizardStore();
const init = store.answers.sms_bower ?? {};
const form = ref({
  enabled: init.enabled ?? false,
  api_key: init.api_key ?? "",
  api_url: init.api_url ?? "https://smsbower.online/stubs/handler_api.php",
  service: init.service ?? "dr",
  country: init.country ?? "0",
  operator: init.operator ?? "",
  max_price: init.max_price ?? "",
  phone_prefix: init.phone_prefix ?? "+",
  timeout_s: init.timeout_s ?? 180,
  poll_interval_s: init.poll_interval_s ?? 5,
  pool_ttl_s: init.pool_ttl_s ?? 1500,
  pool_max_uses: init.pool_max_uses ?? 3,
  pool_path: init.pool_path ?? "",
});

watch(form, () => {
  store.setAnswer("sms_bower", form.value);
  store.saveToServer();
}, { deep: true });
</script>

<style scoped>
code { background: var(--bg-panel); padding: 1px 5px; border: 1px solid var(--border); font-size: 12px; }
.grid-2 { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.grid-3 { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
@media (max-width: 760px) {
  .grid-2,
  .grid-3 { grid-template-columns: 1fr; }
}
</style>
